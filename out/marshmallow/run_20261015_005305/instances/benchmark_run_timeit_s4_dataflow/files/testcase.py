import contextlib
import importlib
import io
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

benchmark = importlib.import_module("performance.benchmark")


def _build_plans(seed, count):
    """Derive CLI argument lists for the benchmark's ``main`` entry point."""
    rng = random.Random(seed)
    plans = []
    for k in range(count):
        roll = rng.randint(0, 99)
        use_profile = roll % 4 == 1
        object_count = rng.randint(3, 12)
        if use_profile:
            iterations = 0
            repeat = 1 + roll % 3
        else:
            iterations = 1 + (roll // 7) % 4
            repeat = 0
        argv = [
            "benchmark.py",
            "--iterations",
            str(iterations),
            "--repeat",
            str(repeat),
            "--object-count",
            str(object_count),
        ]
        if use_profile:
            argv.append("--profile")
        plans.append(argv)
    return plans


class BenchmarkMainTest(unittest.TestCase):
    def test_main_degenerate_runs(self):
        plans = _build_plans(seed=20240611, count=10)
        failures = []
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                for argv in plans:
                    out = io.StringIO()
                    with mock.patch.object(sys, "argv", argv):
                        with contextlib.redirect_stdout(out):
                            try:
                                benchmark.main()
                            except (ArithmeticError, ValueError) as exc:
                                failures.append(type(exc))
                            else:
                                self.assertIn("usec/dump", out.getvalue())
                profiled = any("--profile" in argv for argv in plans)
                self.assertEqual(
                    os.path.exists(os.path.join(tmp, "marshmallow.pprof")), profiled
                )
            finally:
                os.chdir(old_cwd)
        self.assertEqual(len(plans), 10)
        self.assertGreaterEqual(len(failures), 1)
