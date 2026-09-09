import os
import pathlib
import random
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab import lab
from instructlab.configuration import DEFAULTS


class TestConfigurationRootCalls(unittest.TestCase):
    def test_seeded_root_cli_invocations(self):
        rng = random.Random(sum(index * index for index in range(29)))
        tokens = [rng.randrange(10_000, 90_000) for _ in range(19)]
        selected_index = (
            len(tokens) - len(str(sum(tokens))) - int(bool(tokens))
        )
        choices = [index == selected_index for index in range(len(tokens))]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            profile_root = root / "profiles"
            for index, token in enumerate(tokens[:-2]):
                profile_dir = profile_root / f"arch-{token % 5}" / f"cpu-{index % 7}"
                profile_dir.mkdir(parents=True, exist_ok=True)
                (profile_dir / f"profile-{token:05d}.yaml").write_text(
                    "{}\n", encoding="utf-8"
                )

            environment = dict(os.environ)
            environment["HOME"] = str(root)
            environment[DEFAULTS.ILAB_SYSTEM_PROFILE_DIR] = str(profile_root)
            for key in list(environment):
                if key.startswith("XDG_"):
                    del environment[key]

            with mock.patch.dict(os.environ, environment, clear=True):
                DEFAULTS._reset()
                runner = CliRunner()
                results = []
                for index, use_defaults in enumerate(choices):
                    selected_path = (
                        "DEFAULT"
                        if use_defaults
                        else str(root / f"absent-{tokens[index]:05d}.yaml")
                    )
                    results.append(
                        runner.invoke(lab.ilab, ["--config", selected_path, "config"])
                    )

        self.assertTrue(
            all(result.exit_code == results[0].exit_code for result in results)
        )
        self.assertTrue(all(result.output for result in results))
        self.assertEqual(sum(choices), int(any(choices)))
        self.assertGreater(len(set(tokens)), len(tokens) // 2)
