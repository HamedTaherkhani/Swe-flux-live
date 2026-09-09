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
        ]

        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            directory_input = root / "directory-input"
            directory_input.mkdir()

            for index in range(30):
                mode = index % 10
                variable = f"CONFIG_MATRIX_{index * index + 3 * index + 17}"
                candidate = root / f"generated-{index * 37 + 11}.py"
                silent = mode in (1, 2)

                if mode == 0:
                    candidate.write_text(
                        f"VALUE_{index} = {index * index + index}\n"
                        f"lower_{index} = {index + 1}\n",
                        encoding="utf-8",
                    )
                elif mode == 2:
                    candidate = directory_input
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

        self.assertEqual(len(outcomes) + failures, 30)
        self.assertIn(True, outcomes)
        self.assertIn(False, outcomes)
        self.assertGreater(failures, len(outcomes))
