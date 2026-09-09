import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch


ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.llamafactory.model.model_utils import quantization  # noqa: E402


class TestConfigureQuantizationExceptions(unittest.TestCase):
    def _make_args(self, *, quantization_bit: int, quantization_method: str = "bitsandbytes", device_map="auto"):
        return SimpleNamespace(
            quantization_bit=quantization_bit,
            quantization_method=quantization_method,
            quantization_device_map=device_map,
            export_quantization_bit=None,
            compute_dtype=torch.float16,
            double_quantization=True,
            quantization_type="nf4",
        )

    def test_raise_handle_matrix(self):
        config = SimpleNamespace(quantization_config=None)
        tokenizer = object()

        def _fake_bitsandbytes_config(**kwargs):
            return {"kind": "fake_bnb_config", **kwargs}

        with (
            patch.object(quantization, "check_version", autospec=True, return_value=None),
            patch.object(quantization, "is_deepspeed_zero3_enabled", autospec=True, return_value=False),
            patch.object(quantization, "is_fsdp_enabled", autospec=True, return_value=False),
            patch.object(quantization, "BitsAndBytesConfig", side_effect=_fake_bitsandbytes_config),
        ):
            init_kwargs_success = {}
            quantization.configure_quantization(
                config=config,
                tokenizer=tokenizer,
                model_args=self._make_args(quantization_bit=4, quantization_method="bitsandbytes", device_map="auto"),
                init_kwargs=init_kwargs_success,
            )
            self.assertIn("quantization_config", init_kwargs_success)
            self.assertNotIn("device_map", init_kwargs_success)

            with self.assertRaisesRegex(ValueError, "Bitsandbytes only accepts 4-bit or 8-bit quantization."):
                quantization.configure_quantization(
                    config=config,
                    tokenizer=tokenizer,
                    model_args=self._make_args(quantization_bit=3, quantization_method="bitsandbytes", device_map=None),
                    init_kwargs={},
                )

            with self.assertRaisesRegex(ValueError, "EETQ only accepts 8-bit quantization."):
                quantization.configure_quantization(
                    config=config,
                    tokenizer=tokenizer,
                    model_args=self._make_args(quantization_bit=4, quantization_method="eetq", device_map=None),
                    init_kwargs={},
                )

