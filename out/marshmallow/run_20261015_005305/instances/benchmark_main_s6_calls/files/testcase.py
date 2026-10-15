import contextlib
import io
import random
import sys
import unittest
from unittest import mock

from performance import benchmark


def _build_argvs():
    rng = random.Random(20240611)
    argvs = []
    for round_no in range(3):
        objects = rng.randint(2, 6) + round_no
        iterations = (objects * 7) % 4 + 1
        repeat = rng.choice([1, 2, 3])
        argv = ["benchmark.py"]
        # Use abbreviated / "=" forms for some options to vary parsing.
        if round_no % 2:
            argv += [f"--obj={objects}", "--rep", str(repeat)]
        else:
            argv += ["--object-count", str(objects), f"--repeat={repeat}"]
        argv += ["--iter", str(iterations)]
        argvs.append(argv)
    return argvs


class TestBenchmarkMain(unittest.TestCase):
    def test_main_runs_several_configurations(self):
        argvs = _build_argvs()
        outputs = []
        for argv in argvs:
            buf = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
                benchmark.main()
            outputs.append(buf.getvalue())
        self.assertEqual(len(outputs), len(argvs))
        for out in outputs:
            self.assertTrue(out.startswith("Benchmark Result:"))
            self.assertTrue(out.rstrip().endswith("usec/dump"))
