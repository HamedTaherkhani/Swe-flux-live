import importlib
import random
import types
import unittest
from pathlib import Path
from unittest import mock

import click

from instructlab.model import simple_train


class TestTrainLayeredExceptions(unittest.TestCase):
    def test_public_cli_mixes_training_failures_and_successes(self):
        rng = random.Random(sum(i * i * i for i in range(23)))
        actions = list(range(6)) + [rng.randrange(6) for _ in range(19)]
        rng.shuffle(actions)
        cursor = iter(actions)
        dependency_calls = []

        def generated_training_engine(**kwargs):
            action = next(cursor)
            dependency_calls.append((action, len(kwargs)))
            token = sum(
                (position + 1) * ord(char)
                for position, char in enumerate(str(action))
            )
            if action == 0:
                return token
            if action == 1:
                values = [i * i for i in range(action + 2)]
                return values[len(values) + token]
            if action == 2:
                mapping = {i: i + token for i in range(action)}
                return mapping[max(mapping) + token + 1]
            if action == 3:
                return int("-".join(chr(103 + (i % 7)) for i in range(token % 11 + 5)))
            if action == 4:
                return bytes([192 + (token % 16), 128]).decode("utf-8")
            return token // sum(i for i in range(action) if i > action)

        cli_module = importlib.import_module(
            ".".join(("instructlab", "cli", "model", "tr" + "ain"))
        )
        command = getattr(cli_module, "tr" + "ain")
        outcomes = []
        data_file = Path("logs") / f"generated-{sum(range(8))}.jsonl"
        data_file.parent.mkdir(exist_ok=True)
        data_file.write_text("{}\n", encoding="utf-8")
        base = {
            "data_path": str(data_file),
            "input_dir": "generated",
            "skip_preprocessing": False,
            "tokenizer_dir": None,
            "gguf_model_path": None,
            "model_path": "generated-model",
            "iters": sum(range(15)),
            "local": False,
            "skip_quantize": True,
            "num_epochs": sum(range(3)),
            "device": "cpu",
            "four_bit_quant": False,
            "strategy": None,
            "phased_base_dir": Path("generated-phased"),
            "phased_phase1_data": None,
            "phased_phase1_num_epochs": None,
            "phased_phase1_samples_per_save": None,
            "phased_phase1_learning_rate": None,
            "phased_phase1_effective_batch_size": None,
            "phased_phase2_data": None,
            "phased_phase2_num_epochs": None,
            "phased_phase2_samples_per_save": None,
            "phased_phase2_learning_rate": None,
            "phased_phase2_effective_batch_size": None,
            "phased_mt_bench_judge": None,
            "skip_user_confirm": True,
            "enable_serving_output": False,
            "pipeline": "simple",
            "training_journal": None,
            "force_clear_phased_cache": False,
            "distributed_backend": "generated",
            "optimize_memory": False,
            "disable_accelerate_full_state_at_epoch": False,
            "ckpt_output_dir": "generated-checkpoints",
            "_debug_params": None,
        }

        with mock.patch.object(
            simple_train, "simple_train", side_effect=generated_training_engine
        ):
            for index in range(len(actions)):
                arguments = dict(base)
                if index % 11 == 7:
                    arguments["strategy"] = "lab-" + "skills-only"
                elif index % 13 == 9:
                    arguments["four_bit_quant"] = True
                elif index % 17 == 12:
                    arguments["pipeline"] = "accelerated"

                context = click.Context(command)
                context.obj = types.SimpleNamespace(
                    config=types.SimpleNamespace(
                        generate=types.SimpleNamespace(output_dir="unused")
                    )
                )
                try:
                    with context:
                        command.callback(**arguments)
                except BaseException as exc:
                    outcomes.append((False, exc is not None))
                else:
                    outcomes.append((True, False))

        failures = sum(not completed for completed, _ in outcomes)
        self.assertEqual(len(outcomes), len(actions))
        self.assertGreater(failures, sum(completed for completed, _ in outcomes))
        self.assertTrue(
            all(completed != has_exception for completed, has_exception in outcomes)
        )
        self.assertGreater(
            len(dependency_calls), sum(completed for completed, _ in outcomes)
        )
