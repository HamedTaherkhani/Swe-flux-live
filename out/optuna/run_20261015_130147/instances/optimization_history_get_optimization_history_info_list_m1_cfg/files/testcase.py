import random
import unittest

import optuna
from optuna.distributions import FloatDistribution
from optuna.trial import create_trial
from optuna.trial import TrialState
from optuna.visualization import plot_optimization_history


optuna.logging.set_verbosity(optuna.logging.ERROR)

_DIST = {"x": FloatDistribution(-10.0, 10.0)}


def _make_study(seed, n_trials, direction="minimize", p_incomplete=0.0, p_infeasible=None,
                name=None):
    """Build a study whose trials are generated from a seeded RNG."""
    rng = random.Random(seed)
    study = optuna.create_study(direction=direction, study_name=name)
    for _ in range(n_trials):
        x = round(rng.uniform(-10.0, 10.0), 3)
        roll = rng.random()
        if roll < p_incomplete:
            state = TrialState.FAIL if rng.random() < 0.5 else TrialState.PRUNED
            study.add_trial(create_trial(state=state, params={"x": x}, distributions=_DIST))
            continue
        kwargs = {}
        if p_infeasible is not None:
            c = rng.random() - (1.0 - p_infeasible)
            kwargs["constraints"] = {"c0": round(c, 3), "c1": round(-abs(x) / 20.0, 3)}
        study.add_trial(
            create_trial(value=x * x - 3.0 * x, params={"x": x}, distributions=_DIST, **kwargs)
        )
    return study


def _abs_param(trial):
    return abs(trial.params["x"])


class TestOptimizationHistoryScenarios(unittest.TestCase):
    def test_single_minimize_plain(self):
        study = _make_study(seed=11, n_trials=9)
        fig = plot_optimization_history(study)
        self.assertEqual(len(fig.data), 3)

    def test_single_maximize_with_incomplete(self):
        study = _make_study(seed=23, n_trials=14, direction="maximize", p_incomplete=0.3)
        fig = plot_optimization_history(study)
        self.assertGreater(len(fig.data[0].x), 0)

    def test_single_constrained_minimize(self):
        study = _make_study(seed=37, n_trials=12, p_infeasible=0.4)
        fig = plot_optimization_history(study)
        self.assertEqual(len(fig.data[0].x) + len(fig.data[2].x), len(study.trials))

    def test_custom_target_single(self):
        study = _make_study(seed=41, n_trials=8, p_incomplete=0.25)
        fig = plot_optimization_history(study, target=_abs_param, target_name="abs x")
        self.assertEqual(len(fig.data), 2)

    def test_multi_study_mixed_directions(self):
        studies = [
            _make_study(seed=50 + k, n_trials=4 + 2 * k, direction=d, name=f"s{k}")
            for k, d in enumerate(["minimize", "maximize", "minimize"])
        ]
        fig = plot_optimization_history(studies)
        self.assertEqual(len(fig.data), 3 * len(studies))

    def test_only_incomplete_trials(self):
        study = _make_study(seed=61, n_trials=6, p_incomplete=1.0)
        fig = plot_optimization_history(study)
        self.assertEqual(len(fig.data), 0)

    def test_only_incomplete_trials_error_bar(self):
        studies = [_make_study(seed=70 + k, n_trials=3 + k, p_incomplete=1.0) for k in range(2)]
        fig = plot_optimization_history(studies, error_bar=True)
        self.assertEqual(len(fig.data), 0)

    def test_all_infeasible_error_bar(self):
        study = _make_study(seed=83, n_trials=7, p_infeasible=1.5)
        fig = plot_optimization_history(study, error_bar=True)
        self.assertEqual(len(fig.data), 0)

    def test_error_bar_multi_minimize(self):
        studies = [
            _make_study(seed=90 + k, n_trials=5 + 3 * k, p_incomplete=0.2, name=f"eb{k}")
            for k in range(3)
        ]
        fig = plot_optimization_history(studies, error_bar=True)
        self.assertGreaterEqual(len(fig.data), 4)

    def test_error_bar_constrained_maximize(self):
        studies = [
            _make_study(seed=110 + k, n_trials=6 + k, direction="maximize",
                        p_infeasible=0.5, name=f"cm{k}")
            for k in range(2)
        ]
        fig = plot_optimization_history(studies, error_bar=True)
        self.assertGreaterEqual(len(fig.data), 4)

    def test_error_bar_custom_target(self):
        studies = [
            _make_study(seed=130 + k, n_trials=4 + k, p_incomplete=0.15, name=f"ct{k}")
            for k in range(2)
        ]
        fig = plot_optimization_history(
            studies, target=_abs_param, target_name="abs x", error_bar=True
        )
        self.assertEqual(len(fig.data), 2)

    def test_multi_custom_target_constrained(self):
        studies = [
            _make_study(seed=150 + k, n_trials=3 + 2 * k, p_infeasible=0.3,
                        p_incomplete=0.1, name=f"mt{k}")
            for k in range(2)
        ]
        fig = plot_optimization_history(studies, target=_abs_param, target_name="abs x")
        self.assertEqual(len(fig.data), 2 * len(studies))
