import math
import random
import unittest
import warnings

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.importance._ped_anova.evaluator import PedAnovaImportanceEvaluator
from optuna.trial import create_trial
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _make_study(directions, rows):
    """rows: iterable of (params, distributions, values_or_None, state)."""
    study = optuna.create_study(directions=directions)
    for params, dists, values, state in rows:
        if state == TrialState.COMPLETE:
            trial = create_trial(params=params, distributions=dists, values=values, state=state)
        else:
            trial = create_trial(params=params, distributions=dists, state=state)
        study.add_trial(trial)
    return study


class TestPedAnovaEvaluateCallGraph(unittest.TestCase):
    def setUp(self):
        self._ctx = warnings.catch_warnings()
        self._ctx.__enter__()
        warnings.simplefilter("ignore")

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _check(self, result, expected_keys):
        self.assertEqual(set(result), set(expected_keys))
        for v in result.values():
            self.assertTrue(math.isfinite(v))
            self.assertGreaterEqual(v, 0.0)

    def test_single_objective_default(self):
        rng = random.Random(17)
        dists = {
            "x": FloatDistribution(-5.0, 5.0),
            "y": FloatDistribution(0.0, 3.0),
            "n": IntDistribution(1, 9),
        }
        rows = []
        for _ in range(rng.randint(36, 44)):
            p = {"x": rng.uniform(-5, 5), "y": rng.uniform(0, 3), "n": rng.randint(1, 9)}
            rows.append((p, dists, [p["x"] ** 2 + 0.1 * p["y"] + 0.01 * p["n"]], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        result = PedAnovaImportanceEvaluator().evaluate(study)
        self._check(result, dists)

    def test_maximize_region_quantile_global(self):
        rng = random.Random(23)
        dists = {
            "lr": FloatDistribution(1e-4, 1e-1, log=True),
            "depth": IntDistribution(2, 32, log=True),
            "w": FloatDistribution(0.0, 1.0, step=0.05),
        }
        rows = []
        for i in range(30 + rng.randint(0, 8)):
            p = {
                "lr": math.exp(rng.uniform(math.log(1e-4), math.log(1e-1))),
                "depth": rng.choice([2, 3, 5, 8, 13, 21, 32]),
                "w": round(rng.randint(0, 20) * 0.05, 2),
            }
            state = TrialState.FAIL if i % 7 == 6 else TrialState.COMPLETE
            rows.append((p, dists, [-abs(math.log10(p["lr"]) + 2.5) + p["w"]], state))
        study = _make_study(["maximize"], rows)
        evaluator = PedAnovaImportanceEvaluator(
            target_quantile=0.2, region_quantile=0.6, evaluate_on_local=False
        )
        self._check(evaluator.evaluate(study), dists)

    def test_multi_objective_without_target(self):
        rng = random.Random(37)
        dists = {"a": FloatDistribution(0.0, 1.0), "b": FloatDistribution(0.0, 1.0)}
        rows = []
        for _ in range(25 + rng.randint(0, 5)):
            p = {"a": rng.random(), "b": rng.random()}
            rows.append((p, dists, [p["a"], 1.0 - p["a"] + 0.3 * p["b"]], TrialState.COMPLETE))
        study = _make_study(["minimize", "minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.25, region_quantile=0.75)
        self._check(evaluator.evaluate(study), dists)

    def test_multi_objective_with_target(self):
        rng = random.Random(41)
        dists = {
            "a": FloatDistribution(-1.0, 1.0),
            "k": IntDistribution(0, 6),
            "c": CategoricalDistribution(["only"]),
        }
        rows = []
        for _ in range(20 + rng.randint(0, 6)):
            p = {"a": rng.uniform(-1, 1), "k": rng.randint(0, 6), "c": "only"}
            rows.append((p, dists, [p["a"] + p["k"], -p["k"]], TrialState.COMPLETE))
        study = _make_study(["minimize", "maximize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.3)
        result = evaluator.evaluate(study, target=lambda t: t.values[0])
        self._check(result, dists)

    def test_conditional_regimes(self):
        rng = random.Random(53)
        kind = CategoricalDistribution(["svm", "tree"])
        rows = []
        for i in range(32):
            k = "svm" if rng.random() < 0.55 else "tree"
            if k == "svm":
                p = {"kind": k, "C": rng.uniform(0.1, 10.0)}
                d = {"kind": kind, "C": FloatDistribution(0.1, 10.0)}
                v = abs(p["C"] - 3.0)
            else:
                p = {"kind": k, "depth": rng.randint(1, 12)}
                d = {"kind": kind, "depth": IntDistribution(1, 12)}
                v = 0.5 * abs(p["depth"] - 6)
            if i % 5 == 0:
                p["extra"] = rng.uniform(0.0, 1.0)
                d["extra"] = FloatDistribution(0.0, 1.0)
            rows.append((p, d, [v], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.25)
        result = evaluator.evaluate(study, params=["C", "depth", "extra"])
        self._check(result, ["C", "depth", "extra"])

    def test_too_few_finite_trials(self):
        dists = {"x": FloatDistribution(0.0, 1.0), "z": CategoricalDistribution(["p", "q"])}
        rows = [({"x": 0.5, "z": "p"}, dists, [1.0], TrialState.COMPLETE)]
        rows += [({"x": 0.1 * j, "z": "q"}, dists, None, TrialState.FAIL) for j in range(6)]
        rows += [({"x": 0.9, "z": "q"}, dists, [float("inf")], TrialState.COMPLETE)]
        study = _make_study(["minimize"], rows)
        result = PedAnovaImportanceEvaluator().evaluate(study)
        self.assertTrue(all(v == 0.0 for v in result.values()))
        self.assertEqual(set(result), {"x", "z"})

    def test_infinite_values_filtered(self):
        rng = random.Random(67)
        dists = {"u": FloatDistribution(0.0, 10.0), "m": IntDistribution(0, 20, step=4)}
        rows = []
        for i in range(45):
            p = {"u": rng.uniform(0, 10), "m": 4 * rng.randint(0, 5)}
            val = float("inf") if i % 4 == 3 else (p["u"] - 7.0) ** 2 + 0.2 * p["m"]
            rows.append((p, dists, [val], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.15, region_quantile=0.9)
        self._check(evaluator.evaluate(study), dists)

    def test_bad_params_argument(self):
        dists = {"x": FloatDistribution(0.0, 1.0)}
        rows = [({"x": j / 10}, dists, [j], TrialState.COMPLETE) for j in range(10)]
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator()
        with self.assertRaises(TypeError):
            evaluator.evaluate(study, params="x")
        with self.assertRaises(TypeError):
            evaluator.evaluate(study, params=["x", 3])
        with self.assertRaisesRegex(ValueError, "completed trial"):
            evaluator.evaluate(study, params=["x", "ghost"])

    def test_dynamic_search_space_regimes(self):
        rng = random.Random(79)
        narrow = FloatDistribution(0.0, 1.0)
        wide = FloatDistribution(0.0, 10.0)
        tiny = FloatDistribution(5.0, 6.0)
        rows = []
        for i in range(40):
            if i < 18:
                dist = narrow
            elif i < 39:
                dist = wide
            else:
                dist = tiny
            x = rng.uniform(dist.low, dist.high)
            g = rng.randint(0, 4)
            d = {"x": dist, "g": IntDistribution(0, 4)}
            rows.append(({"x": x, "g": g}, d, [abs(x - 0.7) + 0.05 * g], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.2, region_quantile=0.8)
        self._check(evaluator.evaluate(study), ["x", "g"])

    def test_categorical_only_in_bad_trials(self):
        rng = random.Random(83)
        rows = []
        for i in range(36):
            x = rng.uniform(-3, 3)
            p = {"x": x}
            d = {"x": FloatDistribution(-3.0, 3.0)}
            v = x * x
            if i % 3 == 0:
                p["opt"] = rng.choice(["adam", "sgd", "rms"])
                d["opt"] = CategoricalDistribution(["adam", "sgd", "rms"])
                v += 100.0
            rows.append((p, d, [v], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.2)
        self._check(evaluator.evaluate(study), ["x", "opt"])

    def test_three_objectives_hssp(self):
        rng = random.Random(97)
        dists = {
            "p": FloatDistribution(0.0, 1.0),
            "q": IntDistribution(1, 64, log=True),
            "r": IntDistribution(5, 5),
        }
        rows = []
        for _ in range(24 + rng.randint(0, 6)):
            p = {"p": rng.random(), "q": rng.choice([1, 2, 4, 8, 16, 32, 64]), "r": 5}
            vals = [p["p"], math.log2(p["q"]) / 6.0, (1 - p["p"]) * rng.random()]
            rows.append((p, dists, vals, TrialState.COMPLETE))
        study = _make_study(["minimize", "minimize", "minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.2, region_quantile=0.5)
        self._check(evaluator.evaluate(study, params=["q", "p", "r"]), dists)

    def test_target_on_single_objective_global(self):
        rng = random.Random(101)
        dists = {
            "x0": FloatDistribution(0.0, 2.0),
            "x1": FloatDistribution(0.0, 2.0, step=0.25),
            "x2": IntDistribution(-3, 3),
            "x3": FloatDistribution(1.0, 100.0, log=True),
        }
        rows = []
        for i in range(28):
            p = {
                "x0": rng.uniform(0, 2),
                "x1": 0.25 * rng.randint(0, 8),
                "x2": rng.randint(-3, 3),
                "x3": math.exp(rng.uniform(0, math.log(100))),
            }
            rows.append((p, dists, [sum(float(v) for v in p.values())], TrialState.COMPLETE))
        study = _make_study(["minimize"], rows)
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.3, evaluate_on_local=False)
        result = evaluator.evaluate(study, target=lambda t: -t.params["x2"] + t.params["x0"])
        self._check(result, dists)


if __name__ == "__main__":
    unittest.main()
