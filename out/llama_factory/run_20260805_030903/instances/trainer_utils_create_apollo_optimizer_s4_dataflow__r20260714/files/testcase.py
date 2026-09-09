import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

import src.llamafactory.train.trainer_utils as trainer_utils


class RecordingApolloOptimizer(torch.optim.Optimizer):
    def __init__(self, params, **kwargs):
        lr = float(kwargs.get("lr", 0.01))
        super().__init__(params, {"lr": lr})
        self.recorded_kwargs = dict(kwargs)

    def step(self, closure=None):
        del closure
        return None

    def zero_grad(self, set_to_none=True):
        del set_to_none
        return None


class _DummyConfig:
    model_type = "llama"


class TinyModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.config = _DummyConfig()
        self.proj_a = torch.nn.Linear(4, 3, bias=True)
        self.block = torch.nn.Sequential(
            torch.nn.Linear(3, 2, bias=True),
            torch.nn.ReLU(),
        )
        self.proj_b = torch.nn.Linear(2, 2, bias=False)
        self.norm = torch.nn.LayerNorm(2)

        # Keep one 2D parameter frozen so both requires_grad branches execute.
        self.proj_b.weight.requires_grad = False


class TestCreateApolloOptimizerDataFlow(unittest.TestCase):
    def test_observed_reaching_defs(self):
        torch.manual_seed(0)

        training_args = SimpleNamespace(
            optim="adamw_torch",
            gradient_accumulation_steps=1,
            weight_decay=0.1,
            learning_rate=0.01,
        )

        finetuning_args_layerwise = SimpleNamespace(
            apollo_target=["all"],
            freeze_vision_tower=False,
            apollo_rank=8,
            apollo_proj="random",
            apollo_proj_type="std",
            apollo_update_interval=16,
            apollo_scale=1.0,
            apollo_scale_type="channel",
            apollo_scale_front=False,
            apollo_layerwise=True,
        )

        finetuning_args_grouped = SimpleNamespace(
            apollo_target=["proj"],
            freeze_vision_tower=False,
            apollo_rank=4,
            apollo_proj="random",
            apollo_proj_type="left",
            apollo_update_interval=8,
            apollo_scale=2.0,
            apollo_scale_type="tensor",
            apollo_scale_front=True,
            apollo_layerwise=False,
        )

        with patch.object(trainer_utils, "APOLLOAdamW", RecordingApolloOptimizer, create=True):
            with patch.object(
                trainer_utils.Trainer,
                "get_optimizer_cls_and_kwargs",
                return_value=(None, {"lr": training_args.learning_rate}),
            ):
                optimizer_layerwise = trainer_utils._create_apollo_optimizer(
                    model=TinyModel(),
                    training_args=training_args,
                    finetuning_args=finetuning_args_layerwise,
                )
                optimizer_grouped = trainer_utils._create_apollo_optimizer(
                    model=TinyModel(),
                    training_args=training_args,
                    finetuning_args=finetuning_args_grouped,
                )

        self.assertIsInstance(optimizer_layerwise, trainer_utils.DummyOptimizer)
        self.assertIsNotNone(optimizer_layerwise.optimizer_dict)
        self.assertGreater(len(optimizer_layerwise.optimizer_dict), 0)

        self.assertIsInstance(optimizer_grouped, RecordingApolloOptimizer)
        self.assertEqual(len(optimizer_grouped.param_groups), 3)
        self.assertGreater(len(optimizer_grouped.param_groups[2]["params"]), 0)
