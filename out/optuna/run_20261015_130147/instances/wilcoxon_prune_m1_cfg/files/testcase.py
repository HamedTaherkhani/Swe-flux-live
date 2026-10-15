import unittest
import warnings

import numpy as np

import optuna
from optuna.pruners._wilcoxon import WilcoxonPruner
from optuna.trial import TrialState
from optuna.trial import create_trial


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _make_pruner(**kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return WilcoxonPruner(**kwargs)


def _running(values):
    return create_trial(state=TrialState.RUNNING, intermediate_values=dict(values))


def _complete(value, values):
    return create_trial(
        state=TrialState.COMPLETE, value=float(value), intermediate_values=dict(values)
    )


def _series(seed, n, loc, scale):
    rng = np.random.RandomState(seed)
    return [float(v) for v in rng.normal(loc, scale, size=n)]


class TestWilcoxonPruneScenarios(unittest.TestCase):
    def setUp(self):
        self._ctx = warnings.catch_warnings()
        self._ctx.__enter__()
        warnings.simplefilter("ignore")

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _prefix_runs(self, pruner, study, values, steps=None, start=0):
        steps = list(range(len(values))) if steps is None else steps
        out = []
        for k in range(start, len(values) + 1):
            frozen = _running(zip(steps[:k], values[:k]))
            out.append(pruner.prune(study, frozen))
        return out

    def test_empty_then_startup_window(self):
        study = optuna.create_study(direction="minimize")
        best = _series(1, 8, 0.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        pruner = _make_pruner(n_startup_steps=0)
        cur = [b + 0.5 for b in best[:3]]
        res = self._prefix_runs(pruner, study, cur)
        self.assertEqual(len(res), len(cur) + 1)
        self.assertTrue(all(isinstance(r, bool) for r in res))

    def test_no_completed_trial_yet(self):
        study = optuna.create_study(direction="minimize")
        pruner = _make_pruner()
        vals = _series(2, 6, 3.0, 0.2)
        res = self._prefix_runs(pruner, study, vals, start=1)
        self.assertFalse(any(res))

    def test_best_trial_without_intermediates(self):
        study = optuna.create_study(direction="maximize")
        for i in range(3):
            study.add_trial(_complete(float(i) * 0.7, {}))
        pruner = _make_pruner(p_threshold=0.3)
        vals = _series(3, 5, -1.0, 0.5)
        res = self._prefix_runs(pruner, study, vals, start=2)
        self.assertFalse(any(res))

    def test_nonfinite_current_values(self):
        study = optuna.create_study(direction="minimize")
        best = _series(4, 12, 0.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        pruner = _make_pruner()
        rng = np.random.RandomState(44)
        res = []
        for k in range(2, 12):
            vals = [b + 1.0 for b in best[:k]]
            if rng.rand() < 0.5:
                vals[rng.randint(k)] = float(["nan", "inf", "-inf"][rng.randint(3)])
            res.append(pruner.prune(study, _running(enumerate(vals))))
        self.assertEqual(len(res), 10)

    def test_minimize_worse_trial_growing(self):
        study = optuna.create_study(direction="minimize")
        best = _series(5, 20, 1.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        noise = _series(55, 20, 0.6, 0.8)
        cur = [b + n for b, n in zip(best, noise)]
        res = self._prefix_runs(pruner=_make_pruner(), study=study, values=cur, start=1)
        self.assertTrue(any(res))

    def test_maximize_mixed_trial(self):
        study = optuna.create_study(direction="maximize")
        best = _series(6, 18, 5.0, 2.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        worse = _series(7, 10, 2.0, 1.0)
        study.add_trial(_complete(np.mean(worse), enumerate(worse)))
        shift = _series(66, 18, -0.4, 1.0)
        cur = [b + s for b, s in zip(best, shift)]
        res = self._prefix_runs(_make_pruner(p_threshold=0.2), study, cur, start=1)
        self.assertEqual(len(res), len(cur))

    def test_steps_missing_from_best(self):
        study = optuna.create_study(direction="minimize")
        best = _series(8, 10, 0.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        pruner = _make_pruner(p_threshold=0.25)
        cur_steps = [s * 3 for s in range(8)]
        cur = [(best[s] if s < 10 else 0.0) + 0.8 for s in cur_steps]
        res = self._prefix_runs(pruner, study, cur, steps=cur_steps, start=1)
        self.assertEqual(len(res), 8)

    def test_average_safety_guard(self):
        study = optuna.create_study(direction="minimize")
        best = _series(9, 14, 0.0, 0.3)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        cur = [b + 0.2 for b in best]
        for j in range(0, 14, 5):
            cur[j] = best[j] - 6.0
        res = self._prefix_runs(_make_pruner(p_threshold=0.15), study, cur, start=2)
        self.assertEqual(len(res), 13)

    def test_large_startup_steps(self):
        study = optuna.create_study(direction="maximize")
        best = _series(10, 16, 0.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        cur = [b - 0.9 for b in best]
        res = self._prefix_runs(_make_pruner(n_startup_steps=11), study, cur, start=4)
        self.assertTrue(any(res))

    def test_extreme_thresholds(self):
        study = optuna.create_study(direction="minimize")
        best = _series(11, 7, 2.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        cur = [b + d for b, d in zip(best, _series(12, 7, 0.1, 1.5))]
        low = self._prefix_runs(_make_pruner(p_threshold=0.0), study, cur, start=3)
        high = self._prefix_runs(_make_pruner(p_threshold=1.0), study, cur, start=3)
        self.assertFalse(any(low))
        self.assertEqual(len(high), len(low))

    def test_shuffled_step_order(self):
        study = optuna.create_study(direction="maximize")
        best = _series(13, 15, 1.0, 1.0)
        study.add_trial(_complete(np.mean(best), enumerate(best)))
        order = [int(i) for i in np.random.RandomState(14).permutation(15)]
        cur_vals = [best[i] - 0.3 + 0.1 * (i % 4) for i in order]
        res = self._prefix_runs(_make_pruner(), study, cur_vals, steps=order, start=1)
        self.assertEqual(len(res), 15)

    def test_best_selected_among_many(self):
        study = optuna.create_study(direction="minimize")
        rng = np.random.RandomState(15)
        for t in range(5):
            n = int(rng.randint(3, 12))
            vals = [float(v) for v in rng.normal(t * 0.5, 1.0, size=n)]
            study.add_trial(_complete(float(np.mean(vals)), enumerate(vals)))
        best_vals = list(study.best_trial.intermediate_values.values())
        cur = [v + float(rng.normal(0.3, 0.7)) for v in best_vals] + [0.0, 1.0]
        res = self._prefix_runs(_make_pruner(p_threshold=0.3), study, cur, start=1)
        self.assertEqual(len(res), len(cur))
