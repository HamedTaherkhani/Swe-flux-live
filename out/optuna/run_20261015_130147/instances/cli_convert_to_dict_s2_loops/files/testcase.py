import io
import json
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import optuna
from optuna import cli


class TestStudiesFlattenOutput(unittest.TestCase):
    def test_studies_flatten_json(self):
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        rng = random.Random(20240917)
        choices = ("minimize", "maximize")
        with tempfile.TemporaryDirectory() as tmpdir:
            url = "sqlite:///" + os.path.join(tmpdir, "studies.db")
            storage = optuna.storages.RDBStorage(url)
            n_studies = 17 + rng.randint(0, 4)
            for k in range(n_studies):
                n_obj = 1 + (rng.randint(0, 9) * (k + 3)) % 5
                directions = [rng.choice(choices) for _ in range(n_obj)]
                optuna.create_study(
                    storage=storage, study_name=f"study-{k:03d}", directions=directions
                )
            storage.engine.dispose()

            argv = ["optuna", "studies", "--storage", url, "--flatten", "-f", "json", "-q"]
            buf = io.StringIO()
            with mock.patch.object(sys, "argv", argv), redirect_stdout(buf):
                status = cli.main()

        self.assertEqual(status, 0)
        rows = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(len(rows), n_studies)
        for row in rows:
            self.assertIn("name", row)
            self.assertIn("direction_0", row)
            self.assertTrue(all(isinstance(v, (str, int, type(None))) for v in row.values()))


if __name__ == "__main__":
    unittest.main()
