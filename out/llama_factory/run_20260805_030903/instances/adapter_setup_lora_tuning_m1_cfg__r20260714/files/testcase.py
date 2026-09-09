import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from llamafactory.hparams.finetuning_args import FinetuningArguments
from llamafactory.hparams.model_args import ModelArguments
from llamafactory.model import adapter as adapter_module


class DummyTensor:
    def __init__(self) -> None:
        self.cast_dtypes = []

    def to(self, dtype):
        self.cast_dtypes.append(str(dtype))
        return self


class DummyParam:
    def __init__(self, requires_grad: bool = True) -> None:
        self.requires_grad = requires_grad
        self.data = DummyTensor()


class DummyModel:
    def __init__(self, quantization_method=None) -> None:
        self.quantization_method = quantization_method
        self._params = [DummyParam(True), DummyParam(False), DummyParam(True)]
        self.input_embeddings = object()
        self.output_embeddings = object()
        self.merged_adapters = []
        self.peft_calls = []
        self.received_lora_config = None
        self.config = SimpleNamespace()

    def get_input_embeddings(self):
        return self.input_embeddings

    def get_output_embeddings(self):
        return self.output_embeddings

    def named_modules(self):
        return iter(
            [
                ("model.embed_tokens", self.input_embeddings),
                ("lm_head", self.output_embeddings),
                ("model.layers.0.self_attn.q_proj", object()),
            ]
        )

    def parameters(self):
        return iter(self._params)


class FakeMergeWrapper:
    def __init__(self, model: DummyModel, adapter_name: str) -> None:
        self._model = model
        self._adapter_name = adapter_name

    def merge_and_unload(self):
        self._model.merged_adapters.append(self._adapter_name)
        return self._model


class FakePeftModel:
    @staticmethod
    def from_pretrained(model, adapter_name, **kwargs):
        model.peft_calls.append((adapter_name, dict(kwargs)))
        if "is_trainable" in kwargs:
            model.resumed_adapter = adapter_name
            return model
        return FakeMergeWrapper(model, adapter_name)


class FakeLoraConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def fake_get_peft_model(model, lora_config):
    model.received_lora_config = lora_config
    return model


class TestSetupLoraTuningCFG(unittest.TestCase):
    def test_three_distinct_invocation_paths(self):
        config = SimpleNamespace()

        with patch.object(adapter_module, "PeftModel", FakePeftModel), patch.object(
            adapter_module, "LoraConfig", FakeLoraConfig
        ), patch.object(adapter_module, "get_peft_model", fake_get_peft_model), patch.object(
            adapter_module, "is_deepspeed_zero3_enabled", lambda: False
        ), patch.object(
            adapter_module, "find_all_linear_modules", lambda model, freeze_vision_tower: ["q_proj", "k_proj"]
        ), patch.object(
            adapter_module,
            "patch_target_modules",
            lambda model, finetuning_args, targets: list(targets) + ["patched_projection"],
        ):
            model_1 = DummyModel()
            model_args_1 = ModelArguments(model_name_or_path="dummy-model", adapter_name_or_path="mergeA,resumeB")
            finetuning_args_1 = FinetuningArguments(finetuning_type="lora", lora_target="q_proj")
            result_1 = adapter_module._setup_lora_tuning(
                config,
                model_1,
                model_args_1,
                finetuning_args_1,
                is_trainable=True,
                cast_trainable_params_to_fp32=True,
            )
            self.assertIs(result_1, model_1)
            self.assertEqual(model_1.merged_adapters, ["mergeA"])
            self.assertEqual(getattr(model_1, "resumed_adapter", None), "resumeB")

            model_2 = DummyModel()
            model_args_2 = ModelArguments(model_name_or_path="dummy-model", resize_vocab=True)
            finetuning_args_2 = FinetuningArguments(
                finetuning_type="lora",
                lora_target="all",
                pissa_init=True,
                pissa_iter=-1,
            )
            result_2 = adapter_module._setup_lora_tuning(
                config,
                model_2,
                model_args_2,
                finetuning_args_2,
                is_trainable=True,
                cast_trainable_params_to_fp32=True,
            )
            self.assertIs(result_2, model_2)
            self.assertIsNotNone(model_2.received_lora_config)
            self.assertIn("patched_projection", model_2.received_lora_config.kwargs["target_modules"])
            self.assertEqual(set(finetuning_args_2.additional_target), {"embed_tokens", "lm_head"})
            self.assertEqual(model_2.received_lora_config.kwargs["init_lora_weights"], "pissa")

            model_3 = DummyModel()
            model_args_3 = ModelArguments(model_name_or_path="dummy-model", adapter_name_or_path="soloAdapter")
            finetuning_args_3 = FinetuningArguments(finetuning_type="lora", lora_target="q_proj")
            result_3 = adapter_module._setup_lora_tuning(
                config,
                model_3,
                model_args_3,
                finetuning_args_3,
                is_trainable=False,
                cast_trainable_params_to_fp32=True,
            )
            self.assertIs(result_3, model_3)
            self.assertEqual(model_3.merged_adapters, ["soloAdapter"])
            self.assertFalse(hasattr(model_3, "resumed_adapter"))
            self.assertIsNone(model_3.received_lora_config)
