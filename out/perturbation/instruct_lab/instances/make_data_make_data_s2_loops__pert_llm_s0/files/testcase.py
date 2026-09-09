import json
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import instructlab.model.simple_train as simple_train_module


class TestSimpleTrainDataPreparation(unittest.TestCase):
    def test_preprocessing_via_training_entrypoint(self):
        seed = sum(index * index for index in range(29))
        rng = random.Random(seed)
        candidate_total = sum((index % 7) + 2 for index in range(249))

        train_rows = [
            {
                "user": f"ctx-q-{index % 9}-{index // 9}-{rng.randrange(32768):05d}",
                "assistant": f"resp-{(index * 31 + rng.randrange(65536)) % 999983:06d}",
            }
            for index in range(candidate_total)
            if (index * 13 + index // 5 + 3) % 17 not in {2, 5, 11}
        ]
        test_rows = [
            {
                "user": f"eval-{index % 11}-{rng.randrange(16384):05d}",
                "assistant": f"out-{(index * 23 + rng.randrange(8192)) % 999979:06d}",
            }
            for index in range(candidate_total)
            if (index * 7 + index * index) % 19 not in {3, 8, 14}
        ]

        fake_convert = types.ModuleType("instructlab.train.lora_mlx.convert")
        fake_convert.convert_between_mlx_and_pytorch = mock.Mock()
        fake_lora = types.ModuleType("instructlab.train.lora_mlx.lora")
        fake_lora.load_and_train = mock.Mock()
        fake_gguf = types.ModuleType("instructlab.mlx_explore.gguf_convert_to_mlx")
        fake_gguf.load = mock.Mock()
        fake_mlx_utils = types.ModuleType("instructlab.mlx_explore.utils")
        fake_mlx_utils.fetch_tokenizer_from_hub = mock.Mock()

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            for filename, rows in (
                ("train_gen.jsonl", train_rows),
                ("test_gen.jsonl", test_rows),
            ):
                (data_dir / filename).write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )

            fake_modules = {
                fake_convert.__name__: fake_convert,
                fake_lora.__name__: fake_lora,
                fake_gguf.__name__: fake_gguf,
                fake_mlx_utils.__name__: fake_mlx_utils,
            }
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch.object(
                    simple_train_module.utils,
                    "is_macos_with_m_chip",
                    return_value=True,
                ),
            ):
                simple_train_module.simple_train(
                    model_path="synthetic/variant-model-v2",
                    skip_preprocessing=False,
                    skip_quantize=True,
                    gguf_model_path=None,
                    tokenizer_dir=None,
                    data_path=str(data_dir),
                    input_dir=str(data_dir / "scratch-unused-input"),
                    ckpt_output_dir=str(data_dir / "checkpoints"),
                    iters=sum(range(21)),
                    local=True,
                    num_epochs=1,
                    device="cpu",
                    four_bit_quant=False,
                )

            produced = [data_dir / name for name in ("train.jsonl", "valid.jsonl", "test.jsonl")]
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in produced))
            self.assertTrue(fake_convert.convert_between_mlx_and_pytorch.called)
            self.assertTrue(fake_lora.load_and_train.called)
