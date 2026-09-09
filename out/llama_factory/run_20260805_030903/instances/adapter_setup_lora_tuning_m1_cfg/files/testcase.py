import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

from llamafactory.model import adapter as adapter_module


class _ModelHarness:
    def __init__(self, tag, quantization_method=None):
        self.tag = tag
        self.config = SimpleNamespace(model_type="generated")
        self.quantization_method = quantization_method
        self._input = object()
        self._output = object()
        self._parameters = [
            torch.nn.Parameter(torch.tensor(float((tag + index * index) % 29), dtype=torch.float16))
            for index in range(23)
        ]
        self._modules = [
            (f"stack.block_{index}.projection", self._input if index % 7 == 2 else object())
            for index in range(19)
        ]
        self._modules.extend(
            [
                ("generated.input_bank", self._input),
                ("generated.output_bank", self._output),
            ]
        )

    def get_input_embeddings(self):
        return self._input

    def get_output_embeddings(self):
        return self._output

    def named_modules(self):
        return iter(self._modules)

    def parameters(self):
        return iter(self._parameters)


class _AdapterHarness:
    def __init__(self, base, marker):
        self.base = base
        self.marker = marker

    def merge_and_unload(self):
        return self.base

    def parameters(self):
        return self.base.parameters()


class TestAdapterSetupControlFlow(unittest.TestCase):
    def test_seeded_indirect_adapter_scenarios(self):
        rng = random.Random(sum((index + 5) * ord(char) for index, char in enumerate(self.id())))
        adapter_count = rng.randrange(17, 22)
        adapter_names = [
            f"generated-adapter-{index}-{rng.randrange(1000, 9999)}"
            for index in range(adapter_count)
        ]
        calls = {"loaded": 0, "merged": 0, "created": 0, "unsloth": 0}

        def model_args(**overrides):
            values = {
                "adapter_name_or_path": None,
                "adapter_folder": None,
                "offload_folder": None,
                "cache_dir": None,
                "model_revision": "generated-revision",
                "hf_hub_token": None,
                "use_unsloth": False,
                "resize_vocab": False,
                "quantization_bit": None,
            }
            values.update(overrides)
            return SimpleNamespace(**values)

        def tuning_args(**overrides):
            values = {
                "finetuning_type": "lora",
                "pure_bf16": False,
                "use_badam": False,
                "pissa_init": False,
                "pissa_iter": -1,
                "use_dora": False,
                "create_new_adapter": False,
                "lora_target": ["generated_projection"],
                "freeze_vision_tower": False,
                "use_llama_pro": False,
                "freeze_trainable_layers": 3,
                "additional_target": None,
                "lora_rank": 8,
                "lora_alpha": 16,
                "lora_dropout": 0.05,
                "use_rslora": False,
            }
            values.update(overrides)
            return SimpleNamespace(**values)

        def from_pretrained(base, name, **_kwargs):
            calls["loaded"] += 1
            wrapped = _AdapterHarness(base, name)
            original_merge = wrapped.merge_and_unload

            def counted_merge():
                calls["merged"] += 1
                return original_merge()

            wrapped.merge_and_unload = counted_merge
            return wrapped

        def create_adapter(base, _config):
            calls["created"] += 1
            return base

        def create_unsloth(base, _args, _kwargs):
            calls["unsloth"] += 1
            return base

        scenarios = [
            (
                _ModelHarness(rng.randrange(30, 80)),
                model_args(adapter_name_or_path=list(adapter_names)),
                tuning_args(),
                False,
            ),
            (
                _ModelHarness(rng.randrange(80, 130)),
                model_args(adapter_name_or_path=list(reversed(adapter_names))),
                tuning_args(),
                True,
            ),
            (
                _ModelHarness(rng.randrange(130, 180)),
                model_args(resize_vocab=True),
                tuning_args(
                    lora_target=["all"],
                    use_llama_pro=True,
                    pissa_init=True,
                    pissa_iter=rng.randrange(3, 8),
                ),
                True,
            ),
            (
                _ModelHarness(rng.randrange(180, 230)),
                model_args(use_unsloth=True),
                tuning_args(
                    pure_bf16=True,
                    create_new_adapter=True,
                    lora_target=[f"generated_{index}" for index in range(4)],
                ),
                True,
            ),
        ]

        with (
            patch.object(adapter_module, "is_deepspeed_zero3_enabled", return_value=False),
            patch.object(adapter_module.PeftModel, "from_pretrained", side_effect=from_pretrained),
            patch.object(adapter_module, "find_all_linear_modules", return_value=["linear_a", "linear_b"]),
            patch.object(adapter_module, "find_expanded_modules", side_effect=lambda _model, modules, _layers: modules),
            patch.object(adapter_module, "patch_target_modules", side_effect=lambda _model, _args, modules: modules),
            patch.object(adapter_module, "LoraConfig", side_effect=lambda **kwargs: SimpleNamespace(**kwargs)),
            patch.object(adapter_module, "get_peft_model", side_effect=create_adapter),
            patch.object(adapter_module, "get_unsloth_peft_model", side_effect=create_unsloth),
            patch.object(adapter_module.logger, "info_rank0", return_value=None),
            patch.object(adapter_module.logger, "warning_rank0", return_value=None),
        ):
            results = [
                adapter_module.init_adapter(model.config, model, margs, fargs, trainable)
                for model, margs, fargs, trainable in scenarios
            ]

            incompatible = _ModelHarness(rng.randrange(230, 280), quantization_method="generated_ptq")
            with self.assertRaisesRegex(ValueError, "compatible"):
                adapter_module.init_adapter(
                    incompatible.config,
                    incompatible,
                    model_args(quantization_bit=4),
                    tuning_args(use_dora=True),
                    True,
                )

        self.assertEqual(len(results), len(scenarios))
        self.assertGreater(calls["loaded"], adapter_count)
        self.assertGreater(calls["merged"], adapter_count)
        self.assertEqual(calls["created"] + calls["unsloth"], 2)
        self.assertTrue(any(parameter.dtype == torch.float32 for parameter in scenarios[2][0].parameters()))
