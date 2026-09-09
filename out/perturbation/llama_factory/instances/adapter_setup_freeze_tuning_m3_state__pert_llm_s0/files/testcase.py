import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch


ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from llamafactory.model import adapter as adapter_module


class MiniBlock(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.attn = torch.nn.Linear(2, 2, bias=False)
        self.mlp = torch.nn.Linear(2, 2, bias=False)


class FreezeToyModel(torch.nn.Module):
    def __init__(self, config) -> None:
        super().__init__()
        self.config = config
        self.layers = torch.nn.ModuleList([MiniBlock() for _ in range(4)])
        self.embed_tokens = torch.nn.Embedding(8, 2)
        self.output_head = torch.nn.Linear(2, 2, bias=False)


class TestSetupFreezeTuningM3State(unittest.TestCase):
    def test_return_state_across_two_invocations(self):
        torch.manual_seed(0)

        composite_text_config = SimpleNamespace(num_hidden_layers=4)
        composite_config = SimpleNamespace(
            text_config=composite_text_config,
            model_type="minicpmo",
        )
        model_first = FreezeToyModel(config=composite_config)

        finetuning_args_first = SimpleNamespace(
            use_llama_pro=True,
            freeze_trainable_layers=2,
            freeze_trainable_modules=["mlp", "attn", "mlp", "attn"],
            freeze_extra_modules=["output_head", "embed_tokens", "output_head"],
            freeze_vision_tower=True,
            freeze_multi_modal_projector=True,
            freeze_language_model=True,
        )

        adapter_module._setup_freeze_tuning(
            model=model_first,
            finetuning_args=finetuning_args_first,
            is_trainable=True,
            cast_trainable_params_to_fp32=True,
        )

        self.assertTrue(model_first.layers[1].attn.weight.requires_grad)
        self.assertTrue(model_first.layers[3].mlp.weight.requires_grad)
        self.assertTrue(model_first.embed_tokens.weight.requires_grad)
        self.assertFalse(model_first.layers[0].attn.weight.requires_grad)

        plain_config = SimpleNamespace(
            num_hidden_layers=4,
            model_type="minicpmo",
        )
        model_second = FreezeToyModel(config=plain_config)

        finetuning_args_second = SimpleNamespace(
            use_llama_pro=False,
            freeze_trainable_layers=-3,
            freeze_trainable_modules=["mlp", "attn", "all", "mlp", "attn"],
            freeze_extra_modules=["embed_tokens", "output_head", "embed_tokens"],
            freeze_vision_tower=True,
            freeze_multi_modal_projector=True,
            freeze_language_model=True,
        )

        adapter_module._setup_freeze_tuning(
            model=model_second,
            finetuning_args=finetuning_args_second,
            is_trainable=True,
            cast_trainable_params_to_fp32=False,
        )

        self.assertTrue(model_second.layers[0].attn.weight.requires_grad)
        self.assertTrue(model_second.layers[1].attn.weight.requires_grad)
        self.assertTrue(model_second.output_head.weight.requires_grad)
        self.assertFalse(model_second.layers[3].mlp.weight.requires_grad)