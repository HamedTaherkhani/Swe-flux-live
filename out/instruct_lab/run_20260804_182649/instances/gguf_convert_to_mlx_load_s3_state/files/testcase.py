import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class _Array:
    pass


class _Module:
    pass


class _QuantizedLinear:
    @staticmethod
    def quantize_module(*args, **kwargs):
        return None


mlx_package = types.ModuleType("mlx")
mlx_core = types.ModuleType("mlx.core")
mlx_nn = types.ModuleType("mlx.nn")
mlx_core.array = _Array
mlx_core.load = lambda *args, **kwargs: ({}, {})
mlx_nn.Module = _Module
mlx_nn.QuantizedLinear = _QuantizedLinear
mlx_package.core = mlx_core
mlx_package.nn = mlx_nn
sys.modules["mlx"] = mlx_package
sys.modules["mlx.core"] = mlx_core
sys.modules["mlx.nn"] = mlx_nn

fake_mlx_utils = types.ModuleType("instructlab.mlx_explore.utils")
fake_mlx_utils.save_model = lambda *args, **kwargs: None
fake_mlx_utils.fetch_tokenizer_from_hub = lambda *args, **kwargs: None
sys.modules[fake_mlx_utils.__name__] = fake_mlx_utils

fake_convert = types.ModuleType("instructlab.train.lora_mlx.convert")
fake_convert.convert_between_mlx_and_pytorch = lambda *args, **kwargs: None
fake_lora = types.ModuleType("instructlab.train.lora_mlx.lora")
fake_lora.load_and_train = lambda *args, **kwargs: None
fake_make_data = types.ModuleType("instructlab.train.lora_mlx.make_data")
fake_make_data.make_data = lambda *args, **kwargs: None
sys.modules[fake_convert.__name__] = fake_convert
sys.modules[fake_lora.__name__] = fake_lora
sys.modules[fake_make_data.__name__] = fake_make_data

from instructlab.mlx_explore import gguf_convert_to_mlx as converter
from instructlab.model.simple_train import simple_train


class _FakeModel:
    def __init__(self, args):
        self.args = args
        self.model = self
        self.loaded = []

    def load_weights(self, items):
        self.loaded = list(items)


class TestIndirectGgufConversion(unittest.TestCase):
    def test_training_prepares_generated_models(self):
        records = []

        def fake_mx_read(path, return_metadata=False):
            phase = int(Path(path).stem.rsplit("_", 1)[1])
            file_type = (phase * phase + phase) % 5
            if phase == 2:
                file_type = sum(range(4)) + 1

            suffixes = [
                "attn_q.weight",
                "attn_k.weight",
                "attn_v.weight",
                "ffn_gate.weight",
                "ffn_down.weight",
                "ffn_up.weight",
            ]
            weights = {}
            for index, suffix in enumerate(suffixes):
                key = "".join(("b", "l", "k", ".", str(index + phase), ".", suffix))
                weights[key] = sum(
                    ((index + 3) * (item + phase + 2)) % 41 for item in range(23)
                )

            metadata = {
                "general.file_type": file_type,
                "llama.embedding_length": sum(
                    (item * (phase + 3)) % 17 for item in range(29)
                ),
                "llama.block_count": sum(
                    (item + phase) % 7 for item in range(18)
                ),
                "llama.attention.head_count": 1,
                "llama.feed_forward_length": sum(
                    (item * item + phase) % 31 for item in range(21)
                ),
                "llama.attention.head_count_kv": 1,
                "llama.attention.layer_norm_rms_epsilon": (
                    sum((item + phase) % 11 for item in range(27)) + 1
                )
                / 100000,
                "tokenizer.ggml.tokens": [
                    chr(97 + ((item * 7 + phase * 3) % 26))
                    for item in range(37 + phase)
                ],
                "llama.rope.freq_base": sum(
                    (item * 13 + phase) % 47 for item in range(33)
                ),
            }
            records.append((phase, len(weights), len(metadata)))
            return weights, metadata

        def fake_save(path, weights):
            destination = Path(path)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "manifest.txt").write_text(
                str(sum(weights.values())), encoding="utf-8"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoints"
            data = root / "data"
            data.mkdir()

            with (
                mock.patch(
                    "instructlab.model.simple_train.utils.is_macos_with_m_chip",
                    return_value=True,
                ),
                mock.patch.object(converter.mx, "load", side_effect=fake_mx_read),
                mock.patch.object(converter, "Model", _FakeModel),
                mock.patch.object(converter, "save_model", side_effect=fake_save),
                mock.patch.object(
                    converter.nn.QuantizedLinear, "quantize_module"
                ) as quantize,
                mock.patch.object(fake_lora, "load_and_train") as train,
            ):
                for phase in range(4):
                    model_name = "".join(
                        chr(97 + ((phase * 5 + offset * 11) % 26))
                        for offset in range(9)
                    )
                    source = checkpoint / model_name
                    source.mkdir(parents=True)
                    (source / "tokenizer.dat").write_text(
                        str(sum((item + phase) % 19 for item in range(31))),
                        encoding="utf-8",
                    )
                    gguf = root / f"artifact_{phase}.gguf"
                    gguf.write_bytes(bytes((item * (phase + 2)) % 251 for item in range(43)))

                    simple_train(
                        model_path=model_name,
                        skip_preprocessing=True,
                        skip_quantize=bool(phase % 2),
                        gguf_model_path=str(gguf),
                        tokenizer_dir="".join(
                            chr(97 + ((phase + item * 3) % 26)) for item in range(12)
                        ),
                        data_path=str(data),
                        input_dir=str(root / "unused"),
                        ckpt_output_dir=str(checkpoint),
                        iters=sum((item + phase) % 13 for item in range(17)),
                        local=True,
                        num_epochs=phase + 1,
                        device="cpu",
                        four_bit_quant=False,
                    )

        self.assertEqual(len(records), train.call_count)
        self.assertGreater(quantize.call_count, 1)
        self.assertTrue(all(width > 0 and fields > width for _, width, fields in records))
