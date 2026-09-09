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
        seed = sum(index * index for index in range(11))
        rng = random.Random(seed)
        candidate_total = sum((index % 4) + 1 for index in range(19))

        train_rows = [
            {
                "user": f"question-{index}-{rng.randrange(10000):04d}",
                "assistant": f"answer-{(index * index + rng.randrange(10000)) % 10007}",
            }
            for index in range(candidate_total)
            if (index * index + 3 * index + 7) % 11 not in {0, 4}
        ]
        test_rows = [
            {
                "user": f"check-{index}-{rng.randrange(10000):04d}",
                "assistant": f"result-{(index * 17 + rng.randrange(10000)) % 10009}",
            }
            for index in range(candidate_total)
            if (index * 5 + index // 3) % 13 not in {1, 6, 9}
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
                    model_path="synthetic/model",
                    skip_preprocessing=False,
                    skip_quantize=True,
                    gguf_model_path=None,
                    tokenizer_dir=None,
                    data_path=str(data_dir),
                    input_dir=str(data_dir / "unused-input"),
                    ckpt_output_dir=str(data_dir / "checkpoints"),
                    iters=sum(range(9)),
                    local=True,
                    num_epochs=1,
                    device="cpu",
                    four_bit_quant=False,
                )

            produced = [data_dir / name for name in ("train.jsonl", "valid.jsonl", "test.jsonl")]
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in produced))
            self.assertTrue(fake_convert.convert_between_mlx_and_pytorch.called)
            self.assertTrue(fake_lora.load_and_train.called)
