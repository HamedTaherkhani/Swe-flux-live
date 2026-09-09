from types import SimpleNamespace
import unittest
from unittest.mock import patch


def numeric_total(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        return sum(numeric_total(item) for item in value)
    if isinstance(value, dict):
        return sum(numeric_total(item) for item in value.values())
    return 0


class StableResult:
    def __init__(self, metrics):
        self.metrics = metrics

    def __repr__(self):
        return repr(self.metrics)


class GeneratedArguments:
    def __init__(self, seed):
        self.seed = seed
        self.skip_special_tokens = bool(seed % 2)

    def to_dict(self, obey_generation_config=False):
        width = 3 + int(obey_generation_config)
        return {
            f"setting_{index}": (self.seed * (index + 2) + index * index) % 97
            for index in range(width)
        }


class FakeTokenizer:
    def __init__(self, seed):
        self.eos_token_id = seed % 17 + 2
        self.additional_special_tokens_ids = [
            (seed * factor + factor**2) % 41 for factor in range(2, 7)
        ]
        self.pad_token_id = (seed * 3) % 19
        self.padding_side = "".join(chr(code) for code in (114, 105, 103, 104, 116))


class FakeTrainer:
    def __init__(self, seed, events, **kwargs):
        self.seed = seed
        self.events = events
        self.kwargs = kwargs

    def train(self, resume_from_checkpoint=None):
        self.events.append(f"train:{len(str(resume_from_checkpoint))}")
        metrics = {
            f"train_{index}": (self.seed + index * index + 3 * index) % 89
            for index in range(4)
        }
        return StableResult(metrics)

    def save_model(self):
        self.events.append("model")

    def log_metrics(self, prefix, metrics):
        self.events.append(f"log:{prefix}:{len(metrics)}")

    def save_metrics(self, prefix, metrics):
        self.events.append(f"save:{prefix}:{sum(metrics.values()) % 31}")

    def save_state(self):
        self.events.append("state")

    def is_world_process_zero(self):
        return True

    def evaluate(self, metric_key_prefix=None, **kwargs):
        self.events.append(f"evaluate:{len(kwargs)}")
        return {
            f"{metric_key_prefix}_{index}": (numeric_total(kwargs) + self.seed * (index + 1)) % 101
            for index in range(4)
        }

    def predict(self, dataset, metric_key_prefix=None, **kwargs):
        basis = sum(dataset) + numeric_total(kwargs) + self.seed
        self.events.append(f"predict:{len(dataset)}")
        metrics = {
            f"{metric_key_prefix}_{index}": (basis * (index + 2) + index) % 103
            for index in range(4)
        }
        return StableResult(metrics)

    def save_predictions(self, dataset, result, skip_special_tokens):
        self.events.append(f"predictions:{len(dataset)}:{int(skip_special_tokens)}")


class QuietLogger:
    def __init__(self, events):
        self.events = events

    def warning_rank0_once(self, message):
        self.events.append(f"warning:{len(message)}")


class TestSFTWorkflowState(unittest.TestCase):
    def test_public_training_entrypoint(self):
        from llamafactory.train import tuner
        from llamafactory.train.sft import workflow

        fragments = ["".join(chr(97 + (index * 7) % 26) for index in range(9)) for _ in range(5)]
        public_args = {word: index**2 + len(word) for index, word in enumerate(fragments)}
        seed = sum((index + 1) * ord(char) for index, char in enumerate("".join(fragments))) % 997
        events = []
        tokenizer = FakeTokenizer(seed)
        model = SimpleNamespace(
            is_quantized=bool(seed % 3),
            config=SimpleNamespace(_attn_implementation=f"mode-{seed % 7}"),
        )

        model_args = SimpleNamespace(
            block_diag_attn=bool(seed % 2),
            compute_dtype=f"dtype-{seed % 5}",
        )
        data_args = SimpleNamespace(
            ignore_pad_token_for_loss=bool((seed // 2) % 2),
            cutoff_len=seed % 61 + 32,
            eval_num_beams=seed % 4 + 2,
        )
        training_args = SimpleNamespace(
            do_train=True,
            do_eval=True,
            do_predict=True,
            predict_with_generate=False,
            generation_max_length=None,
            generation_num_beams=seed % 3 + 1,
            remove_unused_columns=True,
            resume_from_checkpoint=f"checkpoint-{seed % 23}",
            output_dir=f"/tmp/generated-{seed % 29}",
        )
        finetuning_args = SimpleNamespace(
            stage="sft",
            compute_accuracy=True,
            include_effective_tokens_per_second=True,
            plot_loss=True,
            pissa_convert=False,
            use_swanlab=False,
        )
        generating_args = GeneratedArguments(seed)

        def argument_bundle(_):
            return model_args, data_args, training_args, finetuning_args, generating_args

        dataset_values = [(seed * (index + 5) + index**3) % 113 for index in range(24)]
        dataset_module = {
            "train_dataset": dataset_values,
            "eval_dataset": list(reversed(dataset_values[::2])),
        }
        tokenizer_module = {"tokenizer": tokenizer}

        def trainer_factory(**kwargs):
            events.append(f"trainer:{len(kwargs)}")
            return FakeTrainer(seed, events, **kwargs)

        patches = [
            patch.object(tuner, "read_args", side_effect=lambda args: dict(args)),
            patch.object(tuner, "get_ray_args", return_value=SimpleNamespace(use_ray=False)),
            patch.object(tuner, "get_train_args", side_effect=argument_bundle),
            patch.object(tuner, "LogCallback", side_effect=lambda: f"log-callback-{seed % 13}"),
            patch.object(
                tuner,
                "ReporterCallback",
                side_effect=lambda *args: f"reporter-callback-{sum(map(id, args)) % 17}",
            ),
            patch.object(tuner, "is_ray_available", return_value=False),
            patch.object(workflow, "load_tokenizer", return_value=tokenizer_module),
            patch.object(workflow, "get_template_and_fix_tokenizer", return_value=f"template-{seed % 31}"),
            patch.object(workflow, "get_dataset", return_value=dataset_module),
            patch.object(workflow, "load_model", return_value=model),
            patch.object(
                workflow,
                "SFTDataCollatorWith4DAttentionMask",
                side_effect=lambda **kwargs: {"field_count": len(kwargs), "checksum": seed % 43},
            ),
            patch.object(
                workflow,
                "ComputeAccuracy",
                side_effect=lambda: {"buckets": [(seed + i * i) % 37 for i in range(6)]},
            ),
            patch.object(workflow, "eval_logit_processor", f"processor-{seed % 47}"),
            patch.object(
                workflow,
                "get_logits_processor",
                side_effect=lambda: (seed * 7 + sum(dataset_values)) % 127,
            ),
            patch.object(workflow, "CustomSeq2SeqTrainer", side_effect=trainer_factory),
            patch.object(
                workflow,
                "calculate_tps",
                side_effect=lambda dataset, metrics, stage: (
                    sum(dataset) + sum(metrics.values()) + len(stage) * seed
                )
                % 149,
            ),
            patch.object(workflow, "plot_loss", side_effect=lambda path, keys: events.append(f"plot:{len(keys)}")),
            patch.object(
                workflow,
                "create_modelcard_and_push",
                side_effect=lambda *args: events.append(f"card:{len(args)}"),
            ),
            patch.object(workflow, "logger", QuietLogger(events)),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[
            7
        ], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14], patches[
            15
        ], patches[16], patches[17], patches[18]:
            tuner.run_exp(public_args)

        self.assertTrue(events)
        self.assertTrue(any(item.startswith("train:") for item in events))
        self.assertTrue(any(item.startswith("evaluate:") for item in events))
        self.assertTrue(any(item.startswith("predict:") for item in events))
        self.assertEqual(events[-1].split(":")[0], "card")
