"""Deterministic exercise of the behave venv-context setup chain.

The test drives the behave hook ``before_scenario`` (two frames above the
traced logic) three times.  Each round first builds a synthetic PATH from a
fresh filesystem fixture under a fixed ``/tmp`` root: plain directories,
directories whose parent holds a ``pyvenv.cfg`` marker, directories whose
parent holds a ``conda-meta`` directory, and directories whose parent holds
both markers.  A seeded shuffle interleaves the entries differently per
round, the process environment is patched with that PATH (and with the
local-env flag), and a mocked ``subprocess.check_output`` supplies a
different fake kedro install venv per round.
"""

import os
import random
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from features import environment as feat_env

FIXTURE_ROOT = Path("/tmp/kedro_qa_s3state")

ROUNDS = [
    {"keep": 0, "venv": 13, "conda": 10, "both": 7, "seed": 1042},
    {"keep": 30, "venv": 18, "conda": 16, "both": 12, "seed": 2087},
    {"keep": 1, "venv": 5, "conda": 3, "both": 2, "seed": 1547},
    {"keep": 19, "venv": 12, "conda": 15, "both": 6, "seed": 2671},
    {"keep": 7, "venv": 21, "conda": 17, "both": 10, "seed": 3193},
    {"keep": 14, "venv": 8, "conda": 20, "both": 5, "seed": 4016},
]


def _build_round(index, spec):
    base = FIXTURE_ROOT / ("inv%d" % index)
    entries = []
    for j in range(spec["keep"]):
        keep_dir = base / "keep" / ("e%02d" % j)
        keep_dir.mkdir(parents=True)
        entries.append(keep_dir)
    for j in range(spec["venv"]):
        parent = base / "venvs" / ("v%02d" % j)
        (parent / "bin").mkdir(parents=True)
        (parent / "pyvenv.cfg").touch()
        entries.append(parent / "bin")
    for j in range(spec["conda"]):
        parent = base / "condas" / ("c%02d" % j)
        (parent / "bin").mkdir(parents=True)
        (parent / "conda-meta").mkdir()
        entries.append(parent / "bin")
    for j in range(spec["both"]):
        parent = base / "both" / ("b%02d" % j)
        (parent / "bin").mkdir(parents=True)
        (parent / "pyvenv.cfg").touch()
        (parent / "conda-meta").mkdir()
        entries.append(parent / "bin")
    random.Random(spec["seed"]).shuffle(entries)
    install_venv = base / "install_venv"
    (install_venv / "bin").mkdir(parents=True)
    return entries, install_venv


class TestVenvContextState(unittest.TestCase):
    def test_venv_path_history(self):
        shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)
        self.addCleanup(shutil.rmtree, FIXTURE_ROOT, ignore_errors=True)

        plans = []
        which_outputs = []
        for index, spec in enumerate(ROUNDS, start=1):
            entries, install_venv = _build_round(index, spec)
            plans.append((spec, install_venv, os.pathsep.join(map(str, entries))))
            which_outputs.append(str(install_venv / "bin" / "kedro").encode("utf-8"))

        with mock.patch.object(
            feat_env.subprocess, "check_output", side_effect=which_outputs
        ):
            for spec, install_venv, path_str in plans:
                env_patch = {"BEHAVE_LOCAL_ENV": "1", "PATH": path_str}
                with mock.patch.dict(os.environ, env_patch):
                    context = SimpleNamespace()
                    scenario = SimpleNamespace(tags={feat_env.FRESH_VENV_TAG})
                    feat_env.before_scenario(context, scenario)

                bin_dir = install_venv / "bin"
                self.assertEqual(context.venv_dir, install_venv)
                self.assertEqual(context.bin_dir, bin_dir)
                surviving = context.env["PATH"].split(os.pathsep)
                self.assertEqual(surviving[0], str(bin_dir))
                self.assertEqual(len(surviving), spec["keep"] + 1)
                for entry in surviving[1:]:
                    marker = Path(entry).parent
                    self.assertFalse((marker / "pyvenv.cfg").is_file())
                    self.assertFalse((marker / "conda-meta").is_dir())
                self.assertEqual(
                    context.env["PIP_CONFIG_FILE"], str(install_venv / "pip.conf")
                )
                self.assertTrue((install_venv / "pip.conf").is_file())
                self.assertEqual(context.pip, str(bin_dir / "pip"))
                self.assertEqual(context.python, str(bin_dir / "python"))
                self.assertEqual(context.kedro, str(bin_dir / "kedro"))


if __name__ == "__main__":
    unittest.main()
