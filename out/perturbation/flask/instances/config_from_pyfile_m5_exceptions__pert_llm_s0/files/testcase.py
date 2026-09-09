import os
from pathlib import Path
import tempfile
import unittest

from flask import Flask


class TestConfigEnvironmentLoads(unittest.TestCase):
    def test_generated_configuration_matrix(self):
        app = Flask(__name__)
        outcomes = []
        failures = 0

        expressions = [
            "(",
            "RESULT = 1 / 0",
            "RESULT = [][0]",
            "RESULT = {}['absent']",
            "RESULT = bytes([255]).decode('utf-8')",
            "RESULT = None.missing",
            "RESULT = 1 + 'a'",
            "RESULT = undefined_name_xyz",
            "RESULT = int('not-a-number')",
            "import nonexistent_module_abc123",
        ]

        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            directory_input = root / "directory-input"
            directory_input.mkdir()

            for index in range(98):
                mode = index % 14
                variable = f"CONFIG_MATRIX_{index * index + 5 * index + 23}"
                candidate = root / f"payload-{index * 13 + 5}"
                silent = mode in (1, 2)

                if mode == 0:
                    candidate.write_text(
                        f"VALUE_{index} = {index * index + index}\n"
                        f"MATRIX_{index} = [{index}, {index + 1}, {index + 2}]\n"
                        f"FLAG_{index} = {index % 2 == 0}\n"
                        f"SCALE_{index} = {index * 3 + 7}\n"
                        f"PAIR_{index} = ({index}, {index + 5})\n"
                        f"lower_{index} = {index + 1}\n",
                        encoding="utf-8",
                    )
                elif mode == 2:
                    candidate = (
                        directory_input
                        if (index // 14) % 2 == 0
                        else root
                        / f"payload-{(index - 2) * 13 + 5}"
                        / "nested-target.py"
                    )
                elif mode >= 4:
                    candidate.write_text(expressions[mode - 4] + "\n", encoding="utf-8")

                os.environ[variable] = str(candidate)
                try:
                    try:
                        outcomes.append(app.config.from_envvar(variable, silent=silent))
                    except BaseException:
                        failures += 1
                finally:
                    del os.environ[variable]

        self.assertEqual(len(outcomes) + failures, 98)
        self.assertIn(True, outcomes)
        self.assertIn(False, outcomes)
        self.assertGreater(failures, len(outcomes))
