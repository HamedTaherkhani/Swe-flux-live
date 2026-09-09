from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab.configuration import DEFAULTS


class TestRemoveModelDataFlow(unittest.TestCase):
    def test_cli_generated_model_matrix(self):
        rng = random.Random(8675309)
        runner = CliRunner()
        command = import_module("instructlab.cli.model." + "remove").remove

        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            models_dir = root / "models"
            cache_dir = root / "cache"
            models_dir.mkdir()
            cache_dir.mkdir()
            created_roots = []
            results = []

            with mock.patch.object(
                type(DEFAULTS),
                "OCI_DIR",
                new_callable=mock.PropertyMock,
                return_value=str(cache_dir),
            ):
                for index in range(16):
                    token = "".join(
                        chr(ord("a") + rng.randrange(26)) for _ in range(9)
                    )
                    shape = index % 4

                    if shape < 2:
                        relative = Path(f"weight-{index:02d}-{token}.gguf")
                        disk_path = models_dir / relative
                        disk_path.write_bytes(struct.pack("<I", 0x46554747))
                        model_arg = (
                            str(relative)
                            if shape == 0
                            else f"{models_dir.name}/{relative}"
                        )
                        created_roots.append(disk_path)
                    else:
                        namespace = f"owner-{index:02d}-{token}"
                        relative = Path(namespace) / f"variant-{(index * 7) % 13:02d}"
                        disk_path = models_dir / relative
                        disk_path.mkdir(parents=True)
                        for filename in (
                            "config.json",
                            "tokenizer.json",
                            "tokenizer_config.json",
                        ):
                            (disk_path / filename).write_text(
                                json.dumps({"slot": (index * index + 3) % 17}),
                                encoding="utf-8",
                            )
                        (disk_path / f"weights-{token[:3]}.bin").write_bytes(
                            bytes((index + offset) % 256 for offset in range(32))
                        )
                        model_arg = (
                            str(relative)
                            if shape == 2
                            else f"{models_dir.name}/{relative}"
                        )
                        created_roots.append(
                            models_dir / namespace if shape == 2 else disk_path
                        )

                    cache_relative = (
                        Path(model_arg).relative_to(models_dir.name)
                        if model_arg.startswith(models_dir.name + "/")
                        else Path(model_arg)
                    )
                    if (index * index + index) % 3:
                        cached = cache_dir / cache_relative
                        cached.mkdir(parents=True)
                        (cached / "marker").write_text(token[::-1], encoding="utf-8")

                    results.append(
                        runner.invoke(
                            command,
                            [
                                "--model",
                                model_arg,
                                "--model-dir",
                                str(models_dir),
                                "--force",
                            ],
                        )
                    )

            self.assertTrue(all(result.exit_code == 0 for result in results))
            self.assertTrue(all(not path.exists() for path in created_roots))
            self.assertGreater(sum(len(result.output) for result in results), len(results))
