import random
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import torch

import llamafactory.model.loader as loader_module
import llamafactory.train.test_utils as train_test_utils


class _ParameterHarness:
    def __init__(self, value, dtype):
        self.data = torch.tensor(value, dtype=dtype)
        self.requires_grad = True


class _ModelHarness:
    def __init__(self, config, tag):
        self.config = config
        self.tag = tag
        self.thinker = self
        self.was_evaluated = False
        self._parameters = [
            _ParameterHarness((tag + index * index) % 23, torch.float32 if index % 3 else torch.float16)
            for index in range(18)
        ]

    def requires_grad_(self, enabled):
        for parameter in self._parameters:
            parameter.requires_grad = enabled
        return self

    def parameters(self):
        return iter(self._parameters)

    def eval(self):
        self.was_evaluated = True
        return self

    def train(self):
        self.was_evaluated = False
        return self


class _VisionConfig:
    pass


class _ImageTextConfig:
    pass


class _Seq2SeqConfig:
    pass


class _WaveformConfig:
    pass


class _CausalConfig:
    pass


class TestIndirectModelLoadingCallGraph(unittest.TestCase):
    def test_seeded_recursive_inference_loading(self):
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(self.id())))
        modes = [index % 9 for index in range(19)]
        rng.shuffle(modes)
        state = {"cursor": 0, "created": [], "entry_results": []}
        tokenizer = SimpleNamespace(padding_side="right")

        config_types = [_VisionConfig, _ImageTextConfig, _Seq2SeqConfig, _WaveformConfig, _CausalConfig]

        def make_model_args(mode, ordinal):
            return SimpleNamespace(
                model_name_or_path=f"generated-{ordinal}-{rng.randrange(10_000, 99_999)}",
                trust_remote_code=bool((mode + ordinal) % 2),
                cache_dir=None,
                model_revision="main",
                hf_hub_token=None,
                use_unsloth=(mode == 8),
                adapter_name_or_path=[f"adapter-{ordinal}"] if mode == 8 else None,
                mixture_of_depths="load" if mode == 0 else ("convert" if mode == 7 else None),
                train_from_scratch=(mode == 5),
                compute_dtype=torch.float16,
                print_param_status=False,
            )

        def fake_get_infer_args(_kwargs):
            ordinal = state["cursor"]
            mode = modes[ordinal]
            state["cursor"] += 1
            model_args = make_model_args(mode, ordinal)
            finetuning_args = SimpleNamespace(stage="sft")
            return model_args, SimpleNamespace(), finetuning_args, SimpleNamespace()

        def fake_config_from_pretrained(_path, **_kwargs):
            ordinal = state["cursor"] - 1
            mode = modes[ordinal]
            config_type = config_types[mode % len(config_types)]
            config = config_type()
            config.model_type = "qwen2_5_omni" if mode == 6 else f"generated_type_{mode}"
            config.ordinal = ordinal
            return config

        def build_model(config, tag_offset):
            model = _ModelHarness(config, config.ordinal * 31 + tag_offset)
            state["created"].append(model)
            return model

        def fake_from_pretrained(**kwargs):
            return build_model(kwargs["config"], 7)

        def fake_from_config(config, **_kwargs):
            return build_model(config, 13)

        def fake_load_mod(**kwargs):
            return build_model(kwargs["config"], 17)

        def fake_init_adapter(config, model, _model_args, _finetuning_args, _is_trainable):
            if model is None:
                model = build_model(config, 19)
            if state["cursor"] < len(modes):
                nested = train_test_utils.load_infer_model(marker=(state["cursor"] ** 2 + model.tag) % 101)
                state["entry_results"].append(nested)
            return model

        auto_classes = {
            "AutoModelForVision2Seq": SimpleNamespace(
                _model_mapping={_VisionConfig: object()}, from_pretrained=fake_from_pretrained, from_config=fake_from_config
            ),
            "AutoModelForImageTextToText": SimpleNamespace(
                _model_mapping={_ImageTextConfig: object()},
                from_pretrained=fake_from_pretrained,
                from_config=fake_from_config,
            ),
            "AutoModelForSeq2SeqLM": SimpleNamespace(
                _model_mapping={_Seq2SeqConfig: object()}, from_pretrained=fake_from_pretrained, from_config=fake_from_config
            ),
            "AutoModelForTextToWaveform": SimpleNamespace(
                _model_mapping={_WaveformConfig: object()},
                from_pretrained=fake_from_pretrained,
                from_config=fake_from_config,
            ),
            "AutoModelForCausalLM": SimpleNamespace(
                _model_mapping={}, from_pretrained=fake_from_pretrained, from_config=fake_from_config
            ),
        }

        patches = [
            patch.object(train_test_utils, "get_infer_args", side_effect=fake_get_infer_args),
            patch.object(train_test_utils, "load_tokenizer", return_value={"tokenizer": tokenizer, "processor": None}),
            patch.object(loader_module, "skip_check_imports", return_value=None),
            patch.object(
                loader_module,
                "try_download_" + "model_from_other_hub",
                side_effect=lambda model_args: model_args.model_name_or_path,
            ),
            patch.object(
                loader_module,
                "AutoConfig",
                SimpleNamespace(from_pretrained=fake_config_from_pretrained),
            ),
            patch.object(loader_module, "patch_config", return_value=None),
            patch.object(loader_module, "apply_liger_kernel", return_value=None),
            patch.object(loader_module, "load_mod_pretrained_model", side_effect=fake_load_mod),
            patch.object(loader_module, "convert_pretrained_model_to_mod", side_effect=lambda model, *_args: model),
            patch.object(loader_module, "patch_model", return_value=None),
            patch.object(loader_module, "register_autoclass", return_value=None),
            patch.object(loader_module, "init_adapter", side_effect=fake_init_adapter),
            patch.object(
                loader_module,
                "count_parameters",
                side_effect=lambda model: (
                    sum(parameter.requires_grad for parameter in model._parameters),
                    len(model._parameters),
                ),
            ),
            patch.object(loader_module.logger, "info_rank0", return_value=None),
        ]
        patches.extend(patch.object(loader_module, name, replacement) for name, replacement in auto_classes.items())

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            result = train_test_utils.load_infer_model(marker=sum(modes))

        self.assertIsInstance(result, _ModelHarness)
        self.assertEqual(state["cursor"], len(modes))
        self.assertGreaterEqual(len(state["created"]), len(modes))
        self.assertTrue(all(model.was_evaluated for model in state["created"]))
        self.assertTrue(all(not parameter.requires_grad for model in state["created"] for parameter in model._parameters))
