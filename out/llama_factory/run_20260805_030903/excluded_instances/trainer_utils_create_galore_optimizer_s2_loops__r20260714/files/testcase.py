import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

import src.llamafactory.train.trainer_utils as trainer_utils


class RecordingGaLoreOptimizer(torch.optim.Optimizer):
    def __init__(self, params, **kwargs):
        lr = float(kwargs.get("lr", 0.01))
        super().__init__(params, {"lr": lr})

    def step(self, closure=None):
        del closure
        return None

    def zero_grad(self, set_to_none=True):
        del set_to_none
        return None


class ModelVariantA(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.proj_stack = torch.nn.Sequential(
            torch.nn.Linear(4, 3),
            torch.nn.Tanh(),
            torch.nn.Linear(3, 2),
        )
        self.head_proj = torch.nn.Linear(2, 2, bias=False)
        self.container = torch.nn.ModuleDict(
            {
                "proj_aux": torch.nn.Linear(2, 2),
                "norm": torch.nn.LayerNorm(2),
            }
        )


class ModelVariantB(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.block = torch.nn.Sequential(
            torch.nn.Linear(5, 4),
            torch.nn.ReLU(),
        )
        self.out_proj = torch.nn.Linear(4, 2)


class TestCreateGaloreOptimizerLoops(unittest.TestCase):
    def test_named_modules_loop_iterations(self):
        torch.manual_seed(0)

        training_args = SimpleNamespace(
            optim="adamw_torch",
            gradient_accumulation_steps=1,
            weight_decay=0.1,
            learning_rate=0.01,
        )
        finetuning_args = SimpleNamespace(
            galore_target=["proj"],
            freeze_vision_tower=False,
            galore_rank=8,
            galore_update_interval=16,
            galore_scale=1.0,
            galore_proj_type="std",
            galore_layerwise=False,
        )

        with patch.object(trainer_utils, "GaLoreAdamW", RecordingGaLoreOptimizer, create=True):
            with patch.object(
                trainer_utils.Trainer,
                "get_optimizer_cls_and_kwargs",
                return_value=(None, {"lr": training_args.learning_rate}),
            ):
                optimizer_a = trainer_utils._create_galore_optimizer(
                    model=ModelVariantA(),
                    training_args=training_args,
                    finetuning_args=finetuning_args,
                )
                optimizer_b = trainer_utils._create_galore_optimizer(
                    model=ModelVariantB(),
                    training_args=training_args,
                    finetuning_args=finetuning_args,
                )

        self.assertIsInstance(optimizer_a, RecordingGaLoreOptimizer)
        self.assertIsInstance(optimizer_b, RecordingGaLoreOptimizer)
        self.assertEqual(len(optimizer_a.param_groups), 3)
        self.assertEqual(len(optimizer_b.param_groups), 3)
        self.assertGreater(len(optimizer_a.param_groups[2]["params"]), 0)
        self.assertGreater(len(optimizer_b.param_groups[2]["params"]), 0)
