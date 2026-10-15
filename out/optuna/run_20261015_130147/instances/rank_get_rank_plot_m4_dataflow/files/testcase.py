"""Deterministic scenarios driving optuna.visualization.plot_rank."""

from __future__ import annotations

import random
import unittest

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.trial import create_trial
from optuna.visualization import plot_rank


optuna.logging.set_verbosity(optuna.logging.ERROR)

KINDS = ["lin", "log", "int", "ilog", "cat", "ncat"]
LETTERS = "qwertyuiopasdfghjklzxcvbnm"


def _distribution(kind: str):
    if kind == "lin":
        return FloatDistribution(-3.0, 7.0)
    if kind == "log":
        return FloatDistribution(1e-3, 1e2, log=True)
    if kind == "int":
        return IntDistribution(0, 40)
    if kind == "ilog":
        return IntDistribution(1, 1024, log=True)
    if kind == "cat":
        return CategoricalDistribution(["red", "green", "blue", "cyan"])
    return CategoricalDistribution([2, 3, 5, 7, 11])


def _sample(rng: random.Random, kind: str, dist):
    if kind in ("cat", "ncat"):
        return rng.choice(dist.choices)
    if kind == "log":
        return 10 ** rng.uniform(-3.0, 2.0)
    if kind == "ilog":
        return 2 ** rng.randint(0, 10)
    if kind == "int":
        return rng.randint(0, 40)
    return rng.uniform(-3.0, 7.0)


def _space(seed: int, n_params: int) -> dict:
    space = {}
    for k in range(n_params):
        name = LETTERS[(seed * 5 + k * 7) % len(LETTERS)] + str(k)
        kind = KINDS[(seed * 7 + k * 3 + k * k) % len(KINDS)]
        space[name] = (kind, _distribution(kind))
    return space


def _build_study(seed: int, n_params: int, n_trials: int, drop_every: int = 0):
    rng = random.Random(seed)
    space = _space(seed, n_params)
    study = optuna.create_study()
    for t in range(n_trials):
        params = {}
        dists = {}
        for j, (name, (kind, dist)) in enumerate(space.items()):
            if drop_every and j > 0 and (t + j) % drop_every == 0:
                continue
            params[name] = _sample(rng, kind, dist)
            dists[name] = dist
        value = sum(len(str(v)) for v in params.values()) + rng.random()
        study.add_trial(create_trial(params=params, distributions=dists, value=value))
    return study, list(space)


class TestRankPlotScenarios(unittest.TestCase):
    def _check(self, fig, n_shown: int) -> None:
        if n_shown == 0:
            self.assertEqual(len(fig.data), 0)
        elif n_shown == 2:
            self.assertEqual(len(fig.data), 2)
        else:
            self.assertEqual(len(fig.data), n_shown * n_shown + 1)

    def test_no_completed_trials(self) -> None:
        study = optuna.create_study()
        self._check(plot_rank(study), 0)

    def test_explicit_empty_param_list(self) -> None:
        study, _ = _build_study(seed=1, n_params=3, n_trials=6)
        self._check(plot_rank(study, params=[]), 0)

    def test_single_param_grid(self) -> None:
        study, names = _build_study(seed=2, n_params=3, n_trials=9)
        self._check(plot_rank(study, params=names[1:2]), 1)

    def test_pair_default_order(self) -> None:
        study, names = _build_study(seed=3, n_params=2, n_trials=12)
        self._check(plot_rank(study), 2)

    def test_pair_reversed_explicit(self) -> None:
        study, names = _build_study(seed=4, n_params=2, n_trials=10)
        self._check(plot_rank(study, params=names[::-1]), 2)

    def test_pair_picked_from_wider_space(self) -> None:
        study, names = _build_study(seed=5, n_params=4, n_trials=14)
        self._check(plot_rank(study, params=[names[3], names[0]]), 2)

    def test_triple_default_order(self) -> None:
        study, names = _build_study(seed=6, n_params=3, n_trials=15)
        self._check(plot_rank(study), 3)

    def test_quad_reversed_with_custom_target(self) -> None:
        study, names = _build_study(seed=7, n_params=4, n_trials=11)
        fig = plot_rank(
            study, params=names[::-1], target=lambda t: -t.value, target_name="neg"
        )
        self._check(fig, 4)

    def test_five_params_default_order(self) -> None:
        study, names = _build_study(seed=8, n_params=5, n_trials=18)
        self._check(plot_rank(study), 5)

    def test_quad_with_missing_params(self) -> None:
        study, names = _build_study(seed=9, n_params=4, n_trials=16, drop_every=3)
        self._check(plot_rank(study), 4)

    def test_triple_subset_of_six(self) -> None:
        study, names = _build_study(seed=10, n_params=6, n_trials=13)
        self._check(plot_rank(study, params=sorted(names)[1:4]), 3)

    def test_pair_from_six_odd_positions(self) -> None:
        study, names = _build_study(seed=11, n_params=6, n_trials=8)
        self._check(plot_rank(study, params=names[1::2][:2]), 2)

    def test_six_params_default_order(self) -> None:
        study, names = _build_study(seed=12, n_params=6, n_trials=20, drop_every=4)
        self._check(plot_rank(study), 6)
