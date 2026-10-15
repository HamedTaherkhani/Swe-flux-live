from __future__ import annotations

import unittest

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.tree import DecisionTreeRegressor

from optuna.importance._fanova._tree import _FanovaTree


def _bare_tree(sk_tree, search_spaces: np.ndarray) -> _FanovaTree:
    # Build a _FanovaTree without running __init__ so that the target is invoked directly.
    tree = _FanovaTree.__new__(_FanovaTree)
    tree._tree = sk_tree
    tree._search_spaces = search_spaces
    return tree


def _spaces(lows, highs) -> np.ndarray:
    return np.array([[lo, hi] for lo, hi in zip(lows, highs)], dtype=np.float64)


def _sample(rng: np.random.RandomState, spaces: np.ndarray, n: int) -> np.ndarray:
    return np.column_stack([rng.uniform(lo, hi, size=n) for lo, hi in spaces])


class TestPrecomputeStatistics(unittest.TestCase):
    def _run(self, sk_tree, spaces: np.ndarray) -> np.ndarray:
        stats = _bare_tree(sk_tree, spaces)._precompute_statistics()
        self.assertEqual(stats.shape, (sk_tree.node_count, 2))
        self.assertTrue(np.all(np.isfinite(stats)))
        return stats

    def test_one_dim_sine(self) -> None:
        rng = np.random.RandomState(3)
        spaces = _spaces([0.0], [2.0 * np.pi])
        x = _sample(rng, spaces, 60)
        y = np.sin(x[:, 0]) + 0.1 * rng.randn(60)
        model = DecisionTreeRegressor(max_depth=4, random_state=0).fit(x, y)
        stats = self._run(model.tree_, spaces)
        self.assertAlmostEqual(stats[0, 1], 2.0 * np.pi)

    def test_two_dim_product(self) -> None:
        rng = np.random.RandomState(11)
        spaces = _spaces([-1.0, 0.0], [1.0, 3.0])
        x = _sample(rng, spaces, 80)
        y = x[:, 0] * x[:, 1]
        model = DecisionTreeRegressor(max_depth=3, random_state=1).fit(x, y)
        self._run(model.tree_, spaces)

    def test_constant_target_single_leaf(self) -> None:
        rng = np.random.RandomState(5)
        spaces = _spaces([0.0, 0.0, 0.0], [1.0, 2.0, 0.5])
        x = _sample(rng, spaces, 20)
        y = np.full(20, 0.75)
        model = DecisionTreeRegressor(random_state=0).fit(x, y)
        stats = self._run(model.tree_, spaces)
        self.assertEqual(model.tree_.node_count, 1)
        self.assertAlmostEqual(stats[0, 1], 1.0)

    def test_three_dim_quadratic_min_leaf(self) -> None:
        rng = np.random.RandomState(21)
        spaces = _spaces([0.0, -2.0, 1.0], [1.0, 2.0, 1.5])
        x = _sample(rng, spaces, 120)
        y = (x[:, 0] - 0.3) ** 2 - 0.5 * x[:, 1] + 4.0 * (x[:, 2] - 1.25)
        model = DecisionTreeRegressor(max_depth=5, min_samples_leaf=8, random_state=2).fit(x, y)
        self._run(model.tree_, spaces)

    def test_step_function(self) -> None:
        rng = np.random.RandomState(8)
        spaces = _spaces([0.0, 0.0], [10.0, 1.0])
        x = _sample(rng, spaces, 50)
        y = np.floor(x[:, 0] / 2.5) - 1.5
        model = DecisionTreeRegressor(max_depth=3, random_state=0).fit(x, y)
        self._run(model.tree_, spaces)

    def test_extra_tree_estimator(self) -> None:
        rng = np.random.RandomState(13)
        spaces = _spaces([0.0, 0.0], [1.0, 1.0])
        x = _sample(rng, spaces, 42)
        y = np.where(x[:, 0] + x[:, 1] > 1.0, 2.0, -0.5) + 0.2 * rng.randn(42)
        forest = ExtraTreesRegressor(n_estimators=2, max_depth=3, random_state=4).fit(x, y)
        for est in forest.estimators_:
            self._run(est.tree_, spaces)

    def test_negative_targets_wide_space(self) -> None:
        rng = np.random.RandomState(19)
        spaces = _spaces([-5.0], [5.0])
        x = _sample(rng, spaces, 30)
        y = -np.abs(x[:, 0]) - 0.5
        model = DecisionTreeRegressor(max_leaf_nodes=6, random_state=0).fit(x, y)
        self._run(model.tree_, spaces)

    def test_four_dim_sparse_signal(self) -> None:
        rng = np.random.RandomState(29)
        spaces = _spaces([0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0])
        x = _sample(rng, spaces, 100)
        y = 3.0 * (x[:, 2] > 0.6) + x[:, 3] - 0.4 * x[:, 0]
        model = DecisionTreeRegressor(max_depth=3, random_state=3).fit(x, y)
        self._run(model.tree_, spaces)

    def test_single_split_stump(self) -> None:
        rng = np.random.RandomState(31)
        spaces = _spaces([0.0, 0.0], [4.0, 0.25])
        x = _sample(rng, spaces, 25)
        y = np.exp(-x[:, 0])
        model = DecisionTreeRegressor(max_depth=1, random_state=0).fit(x, y)
        self._run(model.tree_, spaces)

    def test_unbalanced_leaf_budget(self) -> None:
        rng = np.random.RandomState(37)
        spaces = _spaces([0.0, 1.0], [1.0, 2.0])
        x = _sample(rng, spaces, 70)
        y = np.log1p(10.0 * x[:, 0]) * x[:, 1] - 2.0
        model = DecisionTreeRegressor(max_leaf_nodes=9, random_state=5).fit(x, y)
        self._run(model.tree_, spaces)

    def test_shrunken_search_space(self) -> None:
        rng = np.random.RandomState(41)
        data_spaces = _spaces([0.0, 0.0], [1.0, 1.0])
        x = _sample(rng, data_spaces, 45)
        y = np.cos(3.0 * x[:, 0]) + x[:, 1] ** 2
        model = DecisionTreeRegressor(max_depth=3, random_state=6).fit(x, y)
        spaces = _spaces([0.2, 0.05], [0.9, 0.95])
        self._run(model.tree_, spaces)

    def test_mae_criterion_tree(self) -> None:
        rng = np.random.RandomState(43)
        spaces = _spaces([0.0, -1.0, 0.0], [2.0, 1.0, 3.0])
        x = _sample(rng, spaces, 42)
        y = x[:, 0] - x[:, 1] * x[:, 2] + rng.standard_t(2, size=42)
        model = DecisionTreeRegressor(
            criterion="absolute_error", max_depth=3, random_state=7
        ).fit(x, y)
        self._run(model.tree_, spaces)
