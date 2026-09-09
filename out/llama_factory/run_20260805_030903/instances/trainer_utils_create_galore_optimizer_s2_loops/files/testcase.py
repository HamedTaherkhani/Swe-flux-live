import random
import unittest
from types import SimpleNamespace
from unittest import mock

import torch

from llamafactory.train import trainer_utils


class _GeneratedNetwork(torch.nn.Module):
    def __init__(self):
        super().__init__()
        seed = sum((index + 1) * ord(char) for index, char in enumerate("galore-module-walk"))
        rng = random.Random(seed)
        self.entry = torch.nn.Linear(9, 9)
        self.sectors = torch.nn.ModuleDict()

        sector_count = ord("w") % 17 + rng.randrange(13, 19)
        for sector_index in range(sector_count):
            units = torch.nn.ModuleDict()
            unit_count = 2 + rng.randrange(5)
            for unit_index in range(unit_count):
                tag_number = (sector_index * sector_index + 7 * unit_index + rng.randrange(97)) % 101
                selector = (tag_number + sector_index + unit_index) % 3
                if selector == 0:
                    prefix, module = "projection", torch.nn.Linear(9, 9)
                elif selector == 1:
                    prefix, module = "adapter", torch.nn.GELU()
                else:
                    prefix, module = "router", torch.nn.Tanh()
                units[f"{prefix}_{unit_index}_{tag_number}"] = module
            self.sectors[f"sector_{sector_index}_{rng.randrange(1000)}"] = units

        self.exit = torch.nn.Linear(9, 4)

    def __repr__(self):
        return f"{type(self).__name__}()"


class _RecordingOptimizer:
    def __init__(self, param_groups, **kwargs):
        self.param_groups = param_groups
        self.kwargs = kwargs


class TestGaLoreOptimizerLoopBehavior(unittest.TestCase):
    def test_generated_module_tree_via_custom_optimizer(self):
        torch.manual_seed(sum(map(ord, "stable-galore-weights")))
        model = _GeneratedNetwork()
        training_args = SimpleNamespace(
            optim="adamw_torch",
            gradient_accumulation_steps=1,
            learning_rate=1 / ord("d"),
            weight_decay=(ord("g") % 11) / ord("d"),
        )
        finetuning_args = SimpleNamespace(
            use_galore=True,
            galore_target=["projection"],
            freeze_vision_tower=False,
            galore_rank=ord("q") % 19,
            galore_update_interval=ord("z") + ord("G"),
            galore_scale=(ord("k") % 7) / 2,
            galore_proj_type="std",
            galore_layerwise=False,
        )

        optimizer_kwargs = {"lr": training_args.learning_rate, "betas": (0.8, 0.95)}
        with (
            mock.patch.object(trainer_utils, "GaLoreAdamW", _RecordingOptimizer, create=True),
            mock.patch.object(
                trainer_utils.Trainer,
                "get_optimizer_cls_and_kwargs",
                return_value=(object, optimizer_kwargs),
            ),
        ):
            optimizer = trainer_utils.create_custom_optimizer(model, training_args, finetuning_args)

        trainable = {parameter for parameter in model.parameters() if parameter.requires_grad}
        grouped = {
            parameter
            for param_group in optimizer.param_groups
            for parameter in param_group["params"]
        }
        self.assertIsInstance(optimizer, _RecordingOptimizer)
        self.assertEqual(grouped, trainable)
        self.assertTrue(any("rank" in item for item in optimizer.param_groups))
        self.assertTrue(any(item["weight_decay"] == 0.0 for item in optimizer.param_groups))
