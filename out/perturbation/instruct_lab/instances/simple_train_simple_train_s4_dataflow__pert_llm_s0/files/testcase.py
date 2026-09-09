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
        rng = random.Random(2_847_391)
        run_count = 0
        conversion_count = 0
        workdirs = []

        def fake_linux_train(**_kwargs):
            nonlocal run_count
            run_count += 1
            result_dir = Path(workdirs[-1]) / "training-1"
            checkpoint = result_dir / "checkpoint-generated"
            merged = result_dir / "merged_model"
            checkpoint.mkdir(parents=True, exist_ok=True)
            merged.mkdir(parents=True, exist_ok=True)

            checkpoint_names = (
                "added_tokens.json",
                "special_tokens_map.json",
                "tokenizer.json",
                "tokenizer.model",
                "tokenizer_config.json",
            )
            for index, name in enumerate(checkpoint_names):
                payload = (
                    rng.randrange(5_000_000) ^ (index + 3) * run_count * 17
                ) % 1597
                (checkpoint / name).write_text(f"{{\"payload\": {payload}}}")

            for name in ("config.json", "generation_config.json"):
                (merged / name).write_text(f"{{\"run\": {run_count}}}")

            shard_count = 61 + run_count * 23 + rng.randrange(17)
            for index in range(shard_count):
                salt = rng.randrange(120_000)
                shard = merged / f"model-{index:04d}-{salt:05d}-v{run_count}.safetensors"
                shard.write_bytes(
                    bytes((index * 7 + salt + offset) % 256 for offset in range(149))
                )
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
