import datetime
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
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.trial import TrialState


_BASE = datetime.datetime(2023, 3, 14, 9, 26, 53)


def _run_cli(argv):
    buf = io.StringIO()
    with mock.patch.object(sys, "argv", ["optuna"] + argv), redirect_stdout(buf):
        status = cli.main()
    return status, buf.getvalue()


def _table_lines(out):
    return [ln for ln in out.splitlines() if ln.startswith("|") or ln.startswith("+")]


def _make_trial(rng, k, state=TrialState.COMPLETE, values=None, params=None, dists=None,
                user_attrs=None):
    start = _BASE + datetime.timedelta(minutes=7 * k + rng.randint(0, 5))
    micro = rng.choice([0, 0, 250000, rng.randint(1, 999999)])
    complete = start + datetime.timedelta(seconds=rng.randint(1, 3500), microseconds=micro)
    kwargs = dict(
        state=state,
        params=params or {},
        distributions=dists or {},
        user_attrs=user_attrs or {},
    )
    if state == TrialState.COMPLETE:
        if values is not None and len(values) > 1:
            kwargs["values"] = values
        elif values is not None:
            kwargs["value"] = values[0]
    trial = optuna.trial.create_trial(**kwargs)
    trial.datetime_start = start
    trial.datetime_complete = complete
    return trial


class TestDumpTableThroughCli(unittest.TestCase):
    def setUp(self):
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        self._tmp = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + os.path.join(self._tmp.name, "cli.db")
        self.storage = optuna.storages.RDBStorage(self.url)

    def tearDown(self):
        self.storage.engine.dispose()
        self._tmp.cleanup()

    def _populate_single(self, name, seed, n, conditional=False, fail_every=0):
        rng = random.Random(seed)
        study = optuna.create_study(storage=self.storage, study_name=name)
        dists = {
            "lr": FloatDistribution(1e-4, 1.0, log=True),
            "depth": IntDistribution(1, 400),
            "act": CategoricalDistribution(["relu", "tanh", "leaky_relu_variant"]),
        }
        for k in range(n):
            params = {
                "lr": float(f"{10 ** rng.uniform(-4, 0):.{rng.randint(1, 5)}g}"),
                "depth": rng.randint(1, 400),
            }
            if not conditional or rng.random() < 0.6:
                params["act"] = rng.choice(["relu", "tanh", "leaky_relu_variant"])
            used = {p: dists[p] for p in params}
            state = TrialState.COMPLETE
            if fail_every and k % fail_every == fail_every - 1:
                state = TrialState.FAIL
            value = round(rng.uniform(-50, 50) * (k + 1), rng.randint(0, 4))
            study.add_trial(_make_trial(rng, k, state, [value], params, used))
        return study

    def _populate_multi(self, name, seed, n):
        rng = random.Random(seed)
        study = optuna.create_study(
            storage=self.storage, study_name=name, directions=["minimize", "maximize"]
        )
        dists = {"x": FloatDistribution(-10, 10), "y": IntDistribution(0, 9)}
        for k in range(n):
            params = {"x": round(rng.uniform(-10, 10), rng.randint(1, 3)), "y": rng.randint(0, 9)}
            vals = [round(params["x"] ** 2 + params["y"], 3), round(rng.uniform(0, 1000), 1)]
            study.add_trial(_make_trial(rng, k, values=vals, params=params, dists=dists))
        return study

    def test_trials_table_nested_params(self):
        self._populate_single("nested", 11, 18)
        status, out = _run_cli(["trials", "--storage", self.url, "--study-name", "nested",
                                "-f", "table"])
        self.assertEqual(status, 0)
        self.assertEqual(len(_table_lines(out)), 18 + 4)

    def test_trials_table_flatten_conditional_and_failed(self):
        self._populate_single("cond", 23, 21, conditional=True, fail_every=5)
        status, out = _run_cli(["trials", "--storage", self.url, "--study-name", "cond",
                                "-f", "table", "--flatten"])
        self.assertEqual(status, 0)
        self.assertIn("params_lr", out)
        self.assertEqual(len(_table_lines(out)), 21 + 4)

    def test_trials_table_multi_objective_flatten(self):
        self._populate_multi("multi", 37, 16)
        status, out = _run_cli(["trials", "--storage", self.url, "--study-name", "multi",
                                "-f", "table", "--flatten"])
        self.assertEqual(status, 0)
        self.assertIn("values_1", out)

    def test_trials_table_with_user_attrs(self):
        rng = random.Random(41)
        study = optuna.create_study(storage=self.storage, study_name="attrs")
        dist = {"u": IntDistribution(-1000, 1000)}
        for k in range(15):
            ua = {"tag": "t" * rng.randint(1, 9)} if k % 3 else {}
            u = rng.randint(-1000, 1000)
            study.add_trial(_make_trial(rng, k, values=[u / 7.0], params={"u": u}, dists=dist,
                                        user_attrs=ua))
        status, out = _run_cli(["trials", "--storage", self.url, "--study-name", "attrs",
                                "-f", "table", "--flatten"])
        self.assertEqual(status, 0)
        self.assertIn("user_attrs_tag", out)

    def test_best_trial_table(self):
        self._populate_single("best", 53, 19, fail_every=4)
        status, out = _run_cli(["best-trial", "--storage", self.url, "--study-name", "best",
                                "-f", "table", "--flatten"])
        self.assertEqual(status, 0)
        self.assertEqual(len(_table_lines(out)), 5)

    def test_best_trials_table(self):
        self._populate_multi("pareto", 67, 24)
        status, out = _run_cli(["best-trials", "--storage", self.url, "--study-name", "pareto",
                                "-f", "table"])
        self.assertEqual(status, 0)
        self.assertGreater(len(_table_lines(out)), 4)

    def test_studies_table(self):
        rng = random.Random(71)
        for j in range(9):
            name = "s" + "-".join(str(rng.randint(0, 10 ** rng.randint(1, 5))) for _ in range(2))
            study = optuna.create_study(storage=self.storage, study_name=name)
            for k in range(j % 4):
                study.add_trial(_make_trial(rng, k + j, values=[float(k)]))
        status, out = _run_cli(["studies", "--storage", self.url, "-f", "table"])
        self.assertEqual(status, 0)
        self.assertEqual(len(_table_lines(out)), 9 + 4)

    def test_studies_table_flatten_directions(self):
        rng = random.Random(89)
        for j in range(7):
            dirs = [rng.choice(["minimize", "maximize"]) for _ in range(1 + j % 3)]
            optuna.create_study(storage=self.storage, study_name=f"d{j}{'x' * (j * 2)}",
                                directions=dirs)
        status, out = _run_cli(["studies", "--storage", self.url, "-f", "table", "--flatten"])
        self.assertEqual(status, 0)
        self.assertIn("direction_2", out)

    def test_study_names_table(self):
        rng = random.Random(97)
        names = sorted({"".join(rng.choice("abcdefgh") for _ in range(rng.randint(1, 14)))
                        for _ in range(22)})
        for name in names:
            optuna.create_study(storage=self.storage, study_name=name)
        status, out = _run_cli(["study-names", "--storage", self.url, "-f", "table"])
        self.assertEqual(status, 0)
        self.assertEqual(len(_table_lines(out)), len(names) + 4)

    def test_ask_table_flatten_search_space(self):
        optuna.create_study(storage=self.storage, study_name="ask1")
        space = {
            "alpha": {"name": "FloatDistribution",
                      "attributes": {"low": 0.0, "high": 3.0, "log": False, "step": None}},
            "units": {"name": "IntDistribution",
                      "attributes": {"low": 8, "high": 1024, "log": False, "step": 1}},
            "opt": {"name": "CategoricalDistribution",
                    "attributes": {"choices": ["sgd", "adam", "rmsprop"]}},
        }
        for seed in (5, 6, 7):
            status, out = _run_cli(["ask", "--storage", self.url, "--study-name", "ask1",
                                    "--sampler", "RandomSampler",
                                    "--sampler-kwargs", json.dumps({"seed": seed}),
                                    "--search-space", json.dumps(space),
                                    "-f", "table", "--flatten"])
            self.assertEqual(status, 0)
            self.assertIn("params_units", out)

    def test_ask_table_empty_params(self):
        optuna.create_study(storage=self.storage, study_name="ask2")
        for _ in range(2):
            status, out = _run_cli(["ask", "--storage", self.url, "--study-name", "ask2",
                                    "-f", "table"])
            self.assertEqual(status, 0)
            self.assertIn("params", out)

    def test_trials_table_long_study(self):
        self._populate_single("long", 101, 30, conditional=True, fail_every=7)
        status, out = _run_cli(["trials", "--storage", self.url, "--study-name", "long",
                                "-f", "table"])
        self.assertEqual(status, 0)
        self.assertEqual(len(_table_lines(out)), 30 + 4)


if __name__ == "__main__":
    unittest.main()
