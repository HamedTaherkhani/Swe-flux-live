import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

from src.llamafactory.model import loader


class DummyConfig:
    pass


class DummyAutoConfig:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return DummyConfig()


class DummyParam:
    def __init__(self):
        self.data = torch.tensor([1.0], dtype=torch.float32)
        self.requires_grad = True


class DummyModel:
    def __init__(self):
        self.config = SimpleNamespace(model_type="dummy")
        self._params = [DummyParam(), DummyParam()]
        self.mode = "init"

    def requires_grad_(self, flag):
        for param in self._params:
            param.requires_grad = flag
        return self

    def parameters(self):
        return list(self._params)

    def named_parameters(self):
        return [("p0", self._params[0]), ("p1", self._params[1])]

    def eval(self):
        self.mode = "eval"
        return self

    def train(self):
        self.mode = "train"
        return self


class TestLoadModelS6Calls(unittest.TestCase):
    def setUp(self):
        random.seed(0)
        torch.manual_seed(0)
        self._patchers = []

        def _patch(name, value):
            patcher = patch.object(loader, name, value)
            patcher.start()
            self._patchers.append(patcher)

        _patch("skip_check_imports", lambda: None)
        _patch("try_download_model_from_other_hub", lambda model_args: model_args.model_name_or_path)
        _patch("AutoConfig", DummyAutoConfig)
        _patch("patch_config", lambda *args, **kwargs: None)
        _patch("apply_liger_kernel", lambda *args, **kwargs: None)
        _patch("patch_model", lambda *args, **kwargs: None)
        _patch("register_autoclass", lambda *args, **kwargs: None)
        _patch("count_parameters", lambda model: (2, 4))
        _patch("logger", SimpleNamespace(info_rank0=lambda *args, **kwargs: None))

        def _init_adapter(config, model, model_args, finetuning_args, is_trainable):
            return model if model is not None else DummyModel()

        _patch("init_adapter", _init_adapter)

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()

    def _make_model_args(self):
        return SimpleNamespace(
            model_name_or_path="unit-test-model",
            trust_remote_code=False,
            cache_dir=None,
            model_revision="main",
            hf_hub_token=None,
            use_unsloth=True,
            adapter_name_or_path=["adapter-a"],
            mixture_of_depths=None,
            train_from_scratch=False,
            compute_dtype=torch.float16,
            print_param_status=False,
        )

    def _make_finetuning_args(self):
        return SimpleNamespace(stage="pt")

    def _invoke_eval_mode(self):
        return loader.load_model(
            tokenizer=object(),
            model_args=self._make_model_args(),
            finetuning_args=self._make_finetuning_args(),
            is_trainable=False,
            add_valuehead=False,
        )

    def _invoke_train_mode(self):
        return loader.load_model(
            tokenizer=object(),
            model_args=self._make_model_args(),
            finetuning_args=self._make_finetuning_args(),
            is_trainable=True,
            add_valuehead=False,
        )

    def test_invocation_callers(self):
        eval_model = self._invoke_eval_mode()
        train_model = self._invoke_train_mode()
        direct_model = loader.load_model(
            tokenizer=object(),
            model_args=self._make_model_args(),
            finetuning_args=self._make_finetuning_args(),
            is_trainable=False,
            add_valuehead=False,
        )

        self.assertEqual(eval_model.mode, "eval")
        self.assertEqual(train_model.mode, "train")
        self.assertEqual(direct_model.mode, "eval")
        self.assertTrue(all(param.data.dtype == torch.float16 for param in eval_model.parameters()))
