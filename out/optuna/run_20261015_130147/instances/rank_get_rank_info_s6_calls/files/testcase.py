from __future__ import annotations

import math
import unittest

import optuna
from optuna.trial import TrialState
from optuna.visualization import plot_rank


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _warmup_objective(trial: optuna.Trial) -> float:
    a = trial.suggest_float("alpha", 1e-3, 1e1, log=True)
    b = trial.suggest_int("beta", -5, 5)
    return math.log10(a) * b


def _branchy_objective(trial: optuna.Trial) -> float:
    kind = trial.suggest_categorical("kind", ["lin", "sq", "abs"])
    x = trial.suggest_float("x", -4.0, 4.0)
    if kind == "lin":
        lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
        value = x + math.log10(lr)
    elif kind == "sq":
        depth = trial.suggest_int("depth", 1, 6)
        value = x * x - depth
    else:
        value = abs(x) * 2.0
    if value > 3.5:
        raise optuna.TrialPruned()
    if -0.4 < value < 0.0:
        raise RuntimeError("synthetic failure")
    return value


class TestRankPlotTwoStudies(unittest.TestCase):
    def test_plot_rank_on_two_studies(self) -> None:
        warm = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=11))
        warm.optimize(_warmup_objective, n_trials=6)
        fig_warm = plot_rank(warm, target=lambda t: -t.value, target_name="neg")
        self.assertEqual(len(fig_warm.data), 2)

        study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=2024))
        study.optimize(_branchy_objective, n_trials=48, catch=(RuntimeError,))
        complete = study.get_trials(states=(TrialState.COMPLETE,))
        self.assertGreater(len(complete), 10)
        self.assertLess(len(complete), 48)

        fig = plot_rank(study)
        names = sorted({p for t in complete for p in t.params})
        self.assertGreater(len(fig.data), len(names))
