import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llamafactory.eval import evaluator as evaluator_module


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]

    def shuffle(self):
        return _Rows(reversed(self._rows))

    def select(self, indices):
        return _Rows(self._rows[index] for index in indices)


class _EvalTemplate:
    def format_example(self, target_data, support_set, subject_name):
        support_mix = sum(row["signal"] for row in support_set) % 97
        prompt = (
            f"{subject_name}|{target_data['ordinal']}|"
            f"{target_data['signal'] ^ support_mix}"
        )
        return [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": target_data["label"]},
        ]


class _PromptTemplate:
    def encode_oneturn(self, tokenizer, messages):
        text = messages[0]["content"]
        rolling = sum(
            (position + 3) * ord(character)
            for position, character in enumerate(text)
        )
        width = 3 + rolling % 7
        return (
            [2 + (rolling + step * step + 11 * step) % 101 for step in range(width)],
            None,
        )


class _Batch(dict):
    def to(self, _device):
        return self


class _Tokenizer:
    padding_side = "right"

    def pad(self, records, **_kwargs):
        return _Batch(records=list(records))


class TestEvaluatorRuntimeInvariants(unittest.TestCase):
    def test_seeded_public_entrypoint_subject_matrix(self):
        seed = sum((index + 7) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        subject_count = sum((step * step + 3) % 7 for step in range(8))
        categories = ("STEM", "Social Sciences", "Humanities", "Other")
        mapping_payload = {
            f"subject_{index:02d}_{rng.randrange(10_000):04d}": {
                "name": f"Domain {(rng.randrange(1_000_000) ^ (index * 193)):06d}",
                "category": categories[(index * index + rng.randrange(17)) % len(categories)],
            }
            for index in range(subject_count)
        }
        subject_ordinals = {
            subject: ordinal for ordinal, subject in enumerate(mapping_payload)
        }

        def make_dataset(subject):
            ordinal = subject_ordinals[subject]
            split_size = 20 + (ordinal * ordinal + 3 * ordinal) % 9
            local_rng = random.Random(seed ^ sum(map(ord, subject)))
            train_rows = [
                {"signal": local_rng.randrange(1_000_000)}
                for _ in range(7 + ordinal % 5)
            ]
            eval_rows = []
            accumulator = local_rng.randrange(10_000)
            for row_index in range(split_size):
                accumulator = (
                    accumulator * 1_103_515_245 + 12_345 + row_index * (ordinal + 1)
                ) & 0x7FFFFFFF
                eval_rows.append(
                    {
                        "ordinal": row_index,
                        "signal": accumulator,
                        "label": chr(ord("A") + ((accumulator >> 5) ^ row_index) % 4),
                    }
                )
            return {"train": _Rows(train_rows), "validation": _Rows(eval_rows)}

        captured = {}

        def fake_init(instance):
            instance.model_args = SimpleNamespace(
                cache_dir=None, hf_hub_token=None, trust_remote_code=False
            )
            instance.eval_args = SimpleNamespace(
                task="generated_validation",
                task_dir="/virtual/evaluation",
                download_mode="reuse_dataset_if_exists",
                n_shot=5,
                batch_size=4 + seed % 4,
            )
            instance.tokenizer = _Tokenizer()
            instance.template = _PromptTemplate()
            instance.model = SimpleNamespace(device="cpu")
            instance.eval_template = _EvalTemplate()
            instance.choice_inputs = []

        def fake_batch_inference(instance, batch_input):
            predictions = []
            for record in batch_input["records"]:
                token_mix = sum(
                    (position + 1) * token
                    for position, token in enumerate(record["input_ids"])
                )
                predictions.append(chr(ord("A") + (token_mix ^ (token_mix >> 3)) % 4))
            return predictions

        def capture_results(_instance, category_corrects, results):
            captured["category_corrects"] = category_corrects
            captured["results"] = results

        with tempfile.TemporaryDirectory() as temp_dir:
            mapping_path = Path(temp_dir) / "mapping.json"
            mapping_path.write_text(
                json.dumps(mapping_payload, sort_keys=True), encoding="utf-8"
            )
            with (
                patch.object(evaluator_module.Evaluator, "__init__", fake_init),
                patch.object(
                    evaluator_module.Evaluator,
                    "batch_inference",
                    fake_batch_inference,
                ),
                patch.object(
                    evaluator_module.Evaluator, "_save_results", capture_results
                ),
                patch.object(
                    evaluator_module, "cached_file", return_value=str(mapping_path)
                ),
                patch.object(
                    evaluator_module,
                    "load_dataset",
                    side_effect=lambda **kwargs: make_dataset(kwargs["name"]),
                ),
            ):
                evaluator_module.run_eval()

        self.assertEqual(set(captured["results"]), set(mapping_payload))
        self.assertTrue(
            all(
                len(captured["results"][subject])
                == len(make_dataset(subject)["validation"])
                for subject in mapping_payload
            )
        )
        self.assertGreater(
            sum(len(values) for values in captured["results"].values()),
            subject_count,
        )
