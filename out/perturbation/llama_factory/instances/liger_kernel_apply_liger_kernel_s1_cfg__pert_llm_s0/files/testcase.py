import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from llamafactory.model import loader


class TestLigerKernelControlFlow(unittest.TestCase):
    def test_generated_model_loading_scenarios(self):
        calls = []

        def make_backend(name):
            if name.endswith("qwen2"):
                def backend(fused_linear_cross_entropy=True, cross_entropy=False):
                    calls.append((name, fused_linear_cross_entropy, cross_entropy))
            else:
                def backend(**kwargs):
                    calls.append((name, tuple(sorted(kwargs.items()))))
            return backend

        transformer_module = types.ModuleType("liger_kernel.transformers")
        model_types = (
            "gemma",
            "qwen2",
            "gemma",
            "gemma3",
            "paligemma",
            "qwen2",
            "mllama",
            "gemma3_text",
            "phi3",
            "qwen2_vl",
            "mistral",
            "qwen2",
            "mixtral",
            "gemma2",
            "qwen2_5_vl",
            "llama",
            "unsupported_x",
            "qwen2",
            "unsupported_y",
            "unsupported_z",
        )
        for model_type in model_types:
            if model_type != "unsupported":
                backend_name = f"apply_liger_{'kernel'}_to_{model_type}"
                setattr(transformer_module, backend_name, make_backend(model_type))

        package_module = types.ModuleType("liger_kernel")
        package_module.transformers = transformer_module
        fake_model = Mock()
        fake_model.train.return_value = fake_model
        configs = [SimpleNamespace(model_type=model_type) for model_type in model_types]

        common_model_args = {
            "adapter_name_or_path": None,
            "enable_liger_kernel": True,
            "mixture_of_depths": None,
            "model_name_or_path": "generated-model-v2",
            "print_param_status": False,
            "train_from_scratch": False,
            "trust_remote_code": False,
            "use_unsloth": False,
        }

        with (
            patch.dict(
                sys.modules,
                {"liger_kernel": package_module, "liger_kernel.transformers": transformer_module},
            ),
            patch.object(loader, "_get_init_kwargs", return_value={}),
            patch.object(loader, "load_config", side_effect=configs),
            patch.object(loader, "patch_config"),
            patch.object(loader.AutoModelForCausalLM, "from_pretrained", return_value=fake_model),
            patch.object(loader, "patch_model"),
            patch.object(loader, "register_autoclass"),
            patch.object(loader, "init_adapter", side_effect=lambda config, model, *args: model),
            patch.object(loader, "count_parameters", return_value=(sum(range(len(model_types))), len(model_types))),
        ):
            for index, model_type in enumerate(model_types):
                model_args = SimpleNamespace(**common_model_args)
                if index == 0:
                    model_args.enable_liger_kernel = False
                stage = "dpo" if (index * len(model_type)) % 2 else "sft"
                result = loader.load_model(
                    tokenizer=object(),
                    model_args=model_args,
                    finetuning_args=SimpleNamespace(stage=stage),
                    is_trainable=True,
                )
                self.assertIs(result, fake_model)

        self.assertGreater(len(calls), len(model_types) // 2)
        self.assertTrue(any(len(call) == 3 for call in calls))