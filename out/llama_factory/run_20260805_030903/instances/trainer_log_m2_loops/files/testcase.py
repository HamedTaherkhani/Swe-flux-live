import random
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch

import torch
from transformers import Trainer

import llamafactory.train.kto.trainer as trainer_module


class _LocalAccelerator:
    device = torch.device("cpu")

    @staticmethod
    def reduce(value, _operation):
        return value


class TestKTOLoggingLoopDynamics(unittest.TestCase):
    def test_seeded_periodic_logging(self):
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(self.id())))
        trainer = trainer_module.CustomKTOTrainer.__new__(trainer_module.CustomKTOTrainer)
        trainer.accelerator = _LocalAccelerator()
        trainer.control = SimpleNamespace(should_log=True, should_evaluate=False, should_save=False)
        trainer.state = SimpleNamespace(global_step=0)
        trainer.args = SimpleNamespace(save_strategy="steps")
        trainer._globalstep_last_logged = 0
        trainer._total_loss_scalar = 0.0
        trainer._nested_gather = lambda value: value
        trainer._get_learning_rate = lambda: 1.0 / (rng.randrange(70, 95) + 1)
        trainer.store_flos = lambda: None

        captured = []

        def capture_base_log(_self, logs, *_args, **_kwargs):
            captured.append(dict(logs))

        invocation_total = (
            len(self.id().split(".")) + len(type(self).__name__.split("Loop")) + len("KTO")
        )
        with patch.object(trainer_module.Trainer, "log", new=capture_base_log):
            for invocation_index in range(invocation_total):
                width = (
                    len(self.id())
                    + invocation_index * (len("metrics") + rng.randrange(2, 6))
                    + rng.randrange(3, 12)
                ) // 2
                stored = defaultdict(list)
                for metric_index in range(width):
                    sample_count = 2 + (metric_index + invocation_index) % 4
                    stored[f"generated/{invocation_index}/{metric_index}"] = [
                        ((metric_index + 1) * (sample_index + 2) + rng.randrange(19)) / 13.0
                        for sample_index in range(sample_count)
                    ]

                for split_index, split in enumerate(("chosen", "rejected")):
                    if (invocation_index + split_index) % 3:
                        count = 2 + (invocation_index * 3 + split_index) % 7
                        stored[f"count/{split}"] = [float(count)]
                        for key_index, key in enumerate(("rewards", "logps", "logits")):
                            stored[f"{key}/{split}_sum"] = [
                                (count * (key_index + 2) + rng.randrange(11)) / 5.0
                            ]

                trainer._stored_metrics = {"train": stored}
                trainer.state.global_step += 1 + invocation_index % 2
                loss = torch.tensor((rng.randrange(20, 90) + invocation_index) / 17.0)
                Trainer._maybe_log_save_evaluate(
                    trainer,
                    loss,
                    None,
                    None,
                    None,
                    invocation_index / max(invocation_total, 1),
                    None,
                    0.0,
                )

        self.assertEqual(len(captured), invocation_total)
        self.assertTrue(all("loss" in logs for logs in captured))
        self.assertTrue(any("rewards/margins" in logs for logs in captured))
        self.assertGreater(sum(len(logs) for logs in captured), len(self.id()))
