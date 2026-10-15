import unittest
import warnings

import numpy as np

import optuna
from optuna.samplers.nsgaii._crossovers._sbx import SBXCrossover


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _make(**kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SBXCrossover(**kwargs)


def _study(n_objectives):
    if n_objectives == 1:
        return optuna.create_study()
    return optuna.create_study(directions=["minimize"] * n_objectives)


def _bounds(seed, dim):
    gen = np.random.RandomState(seed)
    lows = np.round(gen.uniform(-5.0, 5.0, size=dim), 2)
    widths = np.round(gen.uniform(0.5, 10.0, size=dim), 2)
    return np.stack([lows, lows + widths], axis=1)


def _parents(seed, bounds):
    gen = np.random.RandomState(seed)
    lo = bounds[:, 0]
    hi = bounds[:, 1]
    return np.stack([lo + gen.rand(len(bounds)) * (hi - lo) for _ in range(2)])


class TestSBXCrossoverState(unittest.TestCase):
    def _check(self, child, bounds):
        self.assertEqual(child.shape, (len(bounds),))
        self.assertTrue(np.all(np.isfinite(child)))
        self.assertTrue(np.all(child >= bounds[:, 0] - 1e-9))
        self.assertTrue(np.all(child <= bounds[:, 1] + 1e-9))

    def test_default_single_objective(self):
        bounds = _bounds(3, 4)
        parents = _parents(31, bounds)
        child = _make().crossover(parents, np.random.RandomState(7), _study(1), bounds)
        self._check(child, bounds)

    def test_default_multi_objective(self):
        bounds = _bounds(5, 4)
        parents = _parents(52, bounds)
        child = _make().crossover(parents, np.random.RandomState(8), _study(2), bounds)
        self._check(child, bounds)

    def test_explicit_eta_zero(self):
        bounds = _bounds(9, 3)
        parents = _parents(90, bounds)
        child = _make(eta=0.0).crossover(parents, np.random.RandomState(9), _study(1), bounds)
        self._check(child, bounds)

    def test_large_eta(self):
        bounds = _bounds(11, 3)
        parents = _parents(110, bounds)
        child = _make(eta=50.0).crossover(parents, np.random.RandomState(10), _study(1), bounds)
        self._check(child, bounds)

    def test_always_child_gene_no_swap(self):
        bounds = _bounds(13, 3)
        parents = _parents(130, bounds)
        sbx = _make(eta=5.0, uniform_crossover_prob=0.0, use_child_gene_prob=1.0)
        child = sbx.crossover(parents, np.random.RandomState(11), _study(1), bounds)
        self._check(child, bounds)

    def test_always_swap(self):
        bounds = _bounds(17, 3)
        parents = _parents(170, bounds)
        sbx = _make(eta=3.0, uniform_crossover_prob=1.0, use_child_gene_prob=0.3)
        child = sbx.crossover(parents, np.random.RandomState(12), _study(1), bounds)
        self._check(child, bounds)

    def test_identical_gene_in_parents(self):
        bounds = _bounds(19, 3)
        parents = _parents(190, bounds)
        parents[1, 1] = parents[0, 1]
        child = _make(eta=4.0).crossover(parents, np.random.RandomState(13), _study(1), bounds)
        self._check(child, bounds)

    def test_parents_on_bounds(self):
        bounds = _bounds(23, 3)
        parents = np.stack([bounds[:, 0], bounds[:, 1]])
        parents[0, 2] = (bounds[2, 0] + 3 * bounds[2, 1]) / 4
        child = _make(eta=1.5).crossover(parents, np.random.RandomState(14), _study(1), bounds)
        self._check(child, bounds)

    def test_three_objectives_default_eta(self):
        bounds = _bounds(29, 3)
        parents = _parents(290, bounds)
        sbx = _make(uniform_crossover_prob=0.2, use_child_gene_prob=0.8)
        child = sbx.crossover(parents, np.random.RandomState(15), _study(3), bounds)
        self._check(child, bounds)

    def test_repeated_generations(self):
        bounds = _bounds(31, 3)
        parents = _parents(310, bounds)
        rng = np.random.RandomState(16)
        study = _study(1)
        sbx = _make(eta=2.5)
        for _ in range(2):
            child = sbx.crossover(parents, rng, study, bounds)
            self._check(child, bounds)
            parents = np.stack([parents[1], child])

    def test_unit_cube_many_dims(self):
        dim = 4
        bounds = np.tile(np.array([0.0, 1.0]), (dim, 1))
        gen = np.random.RandomState(37)
        parents = gen.rand(2, dim)
        sbx = _make(eta=8.0, uniform_crossover_prob=0.4, use_child_gene_prob=0.6)
        child = sbx.crossover(parents, np.random.RandomState(17), _study(2), bounds)
        self._check(child, bounds)
