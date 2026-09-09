from __future__ import annotations

from importlib import import_module
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab import lab


class TestGenerateDataFlow(unittest.TestCase):
    def test_cli_branch_matrix(self):
        command_module = import_module("instructlab.cli.data." + "generate")
        runner = CliRunner()

        option_sets = []
        for index in range(3):
            options = [
                "--pipeline",
                "simple",
                "--batch-size",
                str((index * index + index) % 5),
                "--sdg-scale-factor",
                str(index + 1),
            ]
            if index % 2:
                options.extend(["--gpus", str(index + 1), "--detached"])
            if index == 2:
                options.extend(["--model-family", "granite"])
            option_sets.append(options)

        with tempfile.TemporaryDirectory() as output_dir:
            common = ["--output-dir", output_dir]
            with (
                mock.patch.object(command_module, "gen_data") as data_backend,
                mock.patch.object(command_module.time, "strftime", return_value="fixed"),
                mock.patch.object(
                    command_module, "get_model_arch", return_value="test-architecture"
                ),
                mock.patch.object(
                    command_module, "get_sysprompt", return_value="test-system-prompt"
                ),
                mock.patch.object(
                    command_module,
                    "use_legacy_pretraining_format",
                    side_effect=(False, True, False),
                ),
            ):
                results = [
                    runner.invoke(
                        lab.ilab,
                        ["--config", "DEFAULT", "data", "generate", *common, *options],
                    )
                    for options in option_sets
                ]

        self.assertTrue(all(result.exit_code == 0 for result in results))
        self.assertEqual(data_backend.call_count, len(option_sets))
