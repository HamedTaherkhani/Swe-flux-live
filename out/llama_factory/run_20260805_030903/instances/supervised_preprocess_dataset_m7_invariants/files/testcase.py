import random
import unittest
from types import SimpleNamespace

from llamafactory.data import loader as loader_module


class _DatasetHarness:
    def __init__(self, columns):
        self.columns = columns
        self.rows = [
            {name: values[index] for name, values in columns.items()}
            for index in range(len(columns["_prompt"]))
        ]

    def __iter__(self):
        return iter(self.rows)

    def map(self, callback, **_kwargs):
        mapped = callback(self.columns)
        names = list(mapped)
        size = len(mapped[names[0]]) if names else 0
        return [
            {name: mapped[name][index] for name in names}
            for index in range(size)
        ]


class _NoMediaPlugin:
    def process_messages(self, messages, _images, _videos, _audios, _processor):
        return messages

    def process_token_ids(
        self, input_ids, labels, _images, _videos, _audios, _tokenizer, _processor
    ):
        return input_ids, labels


class _DeterministicTemplate:
    efficient_eos = False

    def __init__(self):
        self.mm_plugin = _NoMediaPlugin()

    def encode_multiturn(self, _tokenizer, messages, system, tools):
        text = "|".join(message["content"] for message in messages)
        salt = sum((position + 1) * ord(char) for position, char in enumerate(text))
        salt += len(system or "") * 17 + len(tools or "") * 29
        source_ids = [2 + (salt + step * step) % 41 for step in range(4)]
        target_ids = [47 + (salt * (step + 3)) % 43 for step in range(3)]
        return [(source_ids, target_ids)]


class TestPackedSupervisedRuntime(unittest.TestCase):
    def test_seeded_indirect_packing(self):
        seed = sum((index + 5) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        sample_count = sum((offset * offset + 3) % 11 for offset in range(31))

        columns = {
            "_prompt": [],
            "_response": [],
            "_system": [],
            "_tools": [],
            "_images": [],
            "_videos": [],
            "_audios": [],
        }
        for ordinal in range(sample_count):
            token = rng.randrange(1_000_000)
            prompt_turns = 2 if ordinal % 14 == 0 else 1
            columns["_prompt"].append(
                [
                    {"role": "user", "content": f"request-{ordinal}-{token}-{turn}"}
                    for turn in range(prompt_turns)
                ]
            )
            columns["_response"].append(
                [{"role": "assistant", "content": f"reply-{token ^ (ordinal * 97)}"}]
            )
            columns["_system"].append(f"system-{(token + ordinal) % 23}")
            columns["_tools"].append(None if ordinal % 4 else f"tool-{token % 17}")
            columns["_images"].append(None)
            columns["_videos"].append(None)
            columns["_audios"].append(None)

        dataset = _DatasetHarness(columns)
        data_args = SimpleNamespace(
            packing=True,
            neat_packing=True,
            cutoff_len=64,
            mask_history=False,
            train_on_prompt=False,
            streaming=False,
            preprocessing_num_workers=None,
            overwrite_cache=True,
            preprocessing_batch_size=1_000,
        )
        training_args = SimpleNamespace(
            predict_with_generate=False,
            local_process_index=0,
            should_log=False,
        )
        tokenizer = SimpleNamespace(eos_token_id=1, pad_token_id=0)

        packed = loader_module._get_preprocessed_dataset(
            dataset=dataset,
            data_args=data_args,
            training_args=training_args,
            stage="sft",
            template=_DeterministicTemplate(),
            tokenizer=tokenizer,
        )

        self.assertGreater(len(packed), 0)
        self.assertTrue(
            all(len(row["input_ids"]) == data_args.cutoff_len + 1 for row in packed)
        )
        self.assertTrue(all(row["position_ids"] is not None for row in packed))
