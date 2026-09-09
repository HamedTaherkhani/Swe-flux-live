import importlib
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from instructlab import lab


class TestSimpleTrainDataFlow(unittest.TestCase):
    def test_seeded_model_artifacts(self):
        rng = random.Random(731_209)
        run_count = 0
        conversion_count = 0
        workdirs = []

        def fake_linux_train(**_kwargs):
            nonlocal run_count
            run_count += 1
            result_dir = Path(workdirs[-1]) / f"training-{run_count}"
            checkpoint = result_dir / "checkpoint-generated"
            merged = result_dir / "merged_model"
            checkpoint.mkdir(parents=True)
            merged.mkdir()

            checkpoint_names = (
                "added_tokens.json",
                "special_tokens_map.json",
                "tokenizer.json",
                "tokenizer.model",
                "tokenizer_config.json",
            )
            for index, name in enumerate(checkpoint_names):
                payload = (rng.randrange(1_000_000) ^ (index + 1) * run_count) % 997
                (checkpoint / name).write_text(f"{{\"payload\": {payload}}}")

            for name in ("config.json", "generation_config.json"):
                (merged / name).write_text(f"{{\"run\": {run_count}}}")

            shard_count = 19 + rng.randrange(8)
            for index in range(shard_count):
                salt = rng.randrange(10_000)
                shard = merged / f"model-{index:03d}-{salt:04d}.safetensors"
                shard.write_bytes(bytes((index + salt + offset) % 256 for offset in range(31)))
            return result_dir

        def fake_convert(*, model, pad_vocab):
            nonlocal conversion_count
            conversion_count += 1
            artifact = Path(workdirs[-1]) / f"converted-{conversion_count}.gguf"
            artifact.write_text(f"{Path(model).name}:{int(pad_vocab)}")
            return artifact

        linux_module = types.ModuleType("instructlab.train.linux_train")
        linux_module.linux_train = fake_linux_train
        convert_module = types.ModuleType(
            "instructlab.llamacpp.llamacpp_convert_to_gguf"
        )
        convert_module.convert_llama_to_gguf = fake_convert
        model_module = importlib.import_module(
            "instructlab.model." + "simple_" + "train"
        )

        with tempfile.TemporaryDirectory() as tempdir:
            workdirs.append(tempdir)
            root = Path(tempdir)
            prepared = root / "prepared"
            prepared.mkdir()
            checkpoints = root / "checkpoints"
            defaults = SimpleNamespace(
                CHECKPOINTS_DIR=str(checkpoints),
                DATASETS_DIR=str(root / "datasets"),
            )

            with (
                patch.object(
                    model_module.utils, "is_macos_with_m_chip", return_value=False
                ),
                patch.object(model_module, "DEFAULTS", defaults),
                patch.dict(
                    sys.modules,
                    {
                        "instructlab.train.linux_train": linux_module,
                        "instructlab.llamacpp.llamacpp_convert_to_gguf": convert_module,
                    },
                ),
            ):
                runner = CliRunner()
                common = [
                    "--config=DEFAULT",
                    "model",
                    "train",
                    "--pipeline",
                    "simple",
                    "--data-path",
                    str(prepared),
                    "--device",
                    "cuda",
                ]
                first = runner.invoke(lab.ilab, common + ["--4-bit-quant"])
                second = runner.invoke(lab.ilab, common)

            self.assertEqual(first.exit_code + second.exit_code, 0)
            self.assertIsNone(first.exception)
            self.assertIsNone(second.exception)
            self.assertEqual(run_count, len(workdirs) + 1)
            self.assertEqual(conversion_count, run_count // 2)
            self.assertTrue((checkpoints / "ggml-model-f16.gguf").is_file())

