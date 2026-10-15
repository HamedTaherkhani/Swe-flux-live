import math
import unittest

import optuna
from optuna.importance import FanovaImportanceEvaluator
from optuna.importance import get_param_importances


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _study(seed, n_trials, objective, directions=None):
    sampler = optuna.samplers.RandomSampler(seed=seed)
    if directions is None:
        study = optuna.create_study(sampler=sampler)
    else:
        study = optuna.create_study(directions=directions, sampler=sampler)
    study.optimize(objective, n_trials=n_trials)
    return study


class TestFanovaForestMarginals(unittest.TestCase):
    def _check(self, importances, names):
        self.assertEqual(sorted(importances), sorted(names))
        for v in importances.values():
            self.assertTrue(0.0 <= v <= 1.0 + 1e-9)

    def test_single_float_param(self):
        def objective(trial):
            x = trial.suggest_float("x", -3.0, 3.0)
            return x**2

        study = _study(3, 14, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=3, max_depth=3, seed=0)
        imp = evaluator.evaluate(study)
        self._check(imp, ["x"])
        self.assertAlmostEqual(imp["x"], 1.0)

    def test_two_floats_shallow(self):
        def objective(trial):
            a = trial.suggest_float("a", 0.0, 1.0)
            b = trial.suggest_float("b", -1.0, 1.0)
            return 3 * a + b * b

        study = _study(7, 16, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=2, seed=1)
        imp = evaluator.evaluate(study)
        self._check(imp, ["a", "b"])

    def test_three_params_with_int(self):
        def objective(trial):
            u = trial.suggest_float("u", -2.0, 2.0)
            k = trial.suggest_int("k", 1, 6)
            w = trial.suggest_float("w", 0.0, 5.0)
            return u * k - math.sin(w)

        study = _study(11, 20, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=3, max_depth=4, seed=2)
        imp = evaluator.evaluate(study)
        self._check(imp, ["u", "k", "w"])

    def test_categorical_one_hot(self):
        def objective(trial):
            c = trial.suggest_categorical("c", ["red", "green", "blue"])
            x = trial.suggest_float("x", 0.0, 2.0)
            return {"red": 0.0, "green": 2.5, "blue": -1.0}[c] + x

        study = _study(5, 18, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=3, seed=3)
        imp = evaluator.evaluate(study)
        self._check(imp, ["c", "x"])

    def test_param_subset(self):
        def objective(trial):
            p = trial.suggest_float("p", 0.0, 1.0)
            q = trial.suggest_float("q", 0.0, 1.0)
            r = trial.suggest_float("r", 0.0, 1.0)
            return p - 2 * q + r * p

        study = _study(13, 15, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=3, seed=4)
        imp = evaluator.evaluate(study, params=["q", "r"])
        self._check(imp, ["q", "r"])

    def test_single_valued_param_is_skipped(self):
        def objective(trial):
            fixed = trial.suggest_float("fixed", 1.5, 1.5)
            y = trial.suggest_float("y", -5.0, 5.0)
            return fixed * abs(y)

        study = _study(17, 12, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=5, seed=5)
        imp = evaluator.evaluate(study)
        self._check(imp, ["fixed", "y"])
        self.assertEqual(imp["fixed"], 0.0)

    def test_too_few_trials(self):
        def objective(trial):
            return trial.suggest_float("z", 0.0, 1.0)

        study = _study(19, 1, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=4, max_depth=4, seed=6)
        imp = evaluator.evaluate(study)
        self.assertEqual(imp, {"z": 0.0})

    def test_multi_objective_with_target(self):
        def objective(trial):
            a = trial.suggest_float("a", 0.0, 4.0)
            b = trial.suggest_int("b", 0, 3)
            return a + b, a * b

        study = _study(23, 13, objective, directions=["minimize", "maximize"])
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=3, seed=7)
        imp = evaluator.evaluate(study, target=lambda t: t.values[1])
        self._check(imp, ["a", "b"])

    def test_get_param_importances_normalized(self):
        def objective(trial):
            m = trial.suggest_float("m", 1.0, 100.0, log=True)
            n = trial.suggest_float("n", -1.0, 1.0)
            return math.log(m) * n

        study = _study(29, 17, objective)
        imp = get_param_importances(
            study, evaluator=FanovaImportanceEvaluator(n_trees=3, max_depth=2, seed=8)
        )
        self._check(imp, ["m", "n"])
        self.assertAlmostEqual(sum(imp.values()), 1.0)

    def test_deep_single_tree(self):
        def objective(trial):
            s = trial.suggest_float("s", 0.0, 10.0)
            t = trial.suggest_float("t", 0.0, 10.0)
            return math.floor(s) % 3 + 0.1 * t

        study = _study(31, 22, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=1, max_depth=6, seed=9)
        imp = evaluator.evaluate(study)
        self._check(imp, ["s", "t"])

    def test_two_categoricals(self):
        def objective(trial):
            opt = trial.suggest_categorical("opt", ["sgd", "adam"])
            act = trial.suggest_categorical("act", ["relu", "tanh", "gelu", "silu"])
            return (1.0 if opt == "adam" else 0.0) + len(act) * 0.3

        study = _study(37, 16, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=2, max_depth=4, seed=10)
        imp = evaluator.evaluate(study)
        self._check(imp, ["opt", "act"])

    def test_four_params_many_trees(self):
        def objective(trial):
            vals = [trial.suggest_float(f"v{i}", -1.0, 1.0) for i in range(4)]
            return sum((i + 1) * v * v for i, v in enumerate(vals))

        study = _study(41, 12, objective)
        evaluator = FanovaImportanceEvaluator(n_trees=5, max_depth=2, seed=11)
        imp = evaluator.evaluate(study)
        self._check(imp, ["v0", "v1", "v2", "v3"])
