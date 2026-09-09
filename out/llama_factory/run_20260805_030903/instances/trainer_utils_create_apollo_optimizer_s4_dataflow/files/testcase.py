import random
import unittest
from types import SimpleNamespace
from unittest import mock

import torch

from llamafactory.train import trainer_utils


class _GeneratedApolloNetwork(torch.nn.Module):
    def __init__(self, seed):
        super().__init__()
        rng = random.Random(seed)
        self.config = SimpleNamespace(model_type="bert")
        self.stem = torch.nn.Linear(3, 3)
        self.blocks = torch.nn.ModuleDict()

        block_count = 15 + rng.randrange(4)
        for block_index in range(block_count):
            units = torch.nn.ModuleDict()
            signature = (block_index * block_index + rng.randrange(211)) % 223
            prefix = "matrix" if (signature + block_index) % 3 else "route"
            units[f"{prefix}_{signature}"] = torch.nn.Linear(3, 3)
            if (signature + seed) % 4 == 0:
                units[f"norm_{block_index}"] = torch.nn.LayerNorm(3)
            self.blocks[f"stage_{block_index}_{rng.randrange(10000)}"] = units

        self.lm_head = torch.nn.Linear(3, 2)
        for parameter_index, parameter in enumerate(self.parameters()):
            if (parameter_index * parameter_index + seed) % 19 == 0:
                parameter.requires_grad_(False)


class _RecordingOptimizer:
    def __init__(self, param_groups, **kwargs):
        self.param_groups = param_groups
        self.kwargs = kwargs


class TestApolloOptimizerDataFlow(unittest.TestCase):
    def test_generated_models_through_custom_optimizer(self):
        seed = sum(
            (index + 1) * ord(character)
            for index, character in enumerate(self.id())
        )
        torch.manual_seed(seed % (2**31))
        optimizer_kwargs = {
            "lr": ((seed % 37) + 1) / 10000,
            "betas": (0.81, 0.96),
        }
        optimizers = []

        for scenario in range(2):
            model = _GeneratedApolloNetwork(seed + scenario * 101)
            training_args = SimpleNamespace(
                optim="adamw_torch",
                gradient_accumulation_steps=1,
                learning_rate=optimizer_kwargs["lr"] * (scenario + 1),
                weight_decay=((seed + scenario) % 17 + 1) / 1000,
            )
            finetuning_args = SimpleNamespace(
                use_galore=False,
                use_apollo=True,
                apollo_target=["matrix"] if scenario == 0 else ["all"],
                freeze_vision_tower=False,
                apollo_rank=8 + (seed + scenario) % 9,
                apollo_proj="random",
                apollo_proj_type="std",
                apollo_update_interval=97 + (seed + scenario) % 29,
                apollo_scale=1.0 + scenario / 4,
                apollo_scale_type="channel",
                apollo_scale_front=bool(scenario),
                apollo_layerwise=bool(scenario),
            )

            with (
                mock.patch.object(
                    trainer_utils,
                    "APOLLOAdamW",
                    _RecordingOptimizer,
                    create=True,
                ),
                mock.patch.object(
                    trainer_utils.Trainer,
                    "get_optimizer_cls_and_kwargs",
                    return_value=(object, optimizer_kwargs),
                ),
            ):
                optimizers.append(
                    trainer_utils.create_custom_optimizer(
                        model, training_args, finetuning_args
                    )
                )

        self.assertIsInstance(optimizers[0], _RecordingOptimizer)
        self.assertIsInstance(optimizers[1], trainer_utils.DummyOptimizer)
        self.assertGreater(len(optimizers[0].param_groups), 1)
        self.assertTrue(optimizers[1].optimizer_dict)
        self.assertTrue(
            all(
                isinstance(optimizer, _RecordingOptimizer)
                for optimizer in optimizers[1].optimizer_dict.values()
            )
        )
