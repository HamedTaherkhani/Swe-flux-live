"""Drive the Wilcoxon-pruner tutorial's ``objective`` with small, seeded TSP datasets.

The tutorial module runs a full 50-trial study at import time, so we load only
its imports, class and function definitions (compiled against the real file
path so line numbers match the repository source) and then patch the module
globals ``dataset`` and ``N_SA_ITER`` before calling ``objective`` through a
``FixedTrial``.
"""

import ast
import math
import os
import unittest

import numpy as np
import optuna


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if not os.path.isdir(os.path.join(REPO_ROOT, "tutorial")):
    REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TUTORIAL_PATH = os.path.join(REPO_ROOT, "tutorial", "20_recipes", "013_wilcoxon_pruner.py")
MODULE_NAME = "tutorial.20_recipes.013_wilcoxon_pruner"


def load_tutorial_namespace():
    with open(TUTORIAL_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=TUTORIAL_PATH)
    keep = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)
    tree.body = [node for node in tree.body if isinstance(node, keep)]
    code = compile(tree, TUTORIAL_PATH, "exec")
    ns = {"__name__": MODULE_NAME, "__file__": TUTORIAL_PATH, "num_evaluation": 0}
    exec(code, ns)
    return ns


def clustered_problem(rng, num_vertex, num_clusters):
    centers = rng.random((num_clusters, 2))
    labels = np.arange(num_vertex) % num_clusters
    return centers[labels] + 0.05 * rng.standard_normal((num_vertex, 2))


def ring_problem(rng, num_vertex, noise):
    angles = np.sort(rng.random(num_vertex)) * 2.0 * math.pi
    radius = 0.5 + noise * rng.standard_normal(num_vertex)
    return np.stack([radius * np.cos(angles), radius * np.sin(angles)], axis=-1)


class TestWilcoxonTutorialObjective(unittest.TestCase):
    def run_objective(self, seed, problems, n_iter, t0, alpha, patience):
        ns = load_tutorial_namespace()
        ns["dataset"] = np.stack(problems)
        ns["N_SA_ITER"] = n_iter
        np.random.seed(seed)
        trial = optuna.trial.FixedTrial({"T0": t0, "alpha": alpha, "patience": patience})
        value = ns["objective"](trial)
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, 0.0)
        self.assertEqual(ns["num_evaluation"], len(problems))
        return value

    def test_uniform_hot_short_patience(self):
        rng = np.random.default_rng(11)
        problems = [rng.random((9, 2)) for _ in range(2)]
        self.run_objective(1, problems, 24, 5.0, 1.5, 10)

    def test_uniform_cold_schedule(self):
        rng = np.random.default_rng(12)
        problems = [rng.random((12, 2)) for _ in range(2)]
        self.run_objective(2, problems, 20, 0.01, 3.0, 10)

    def test_clustered_three_problems(self):
        rng = np.random.default_rng(13)
        problems = [clustered_problem(rng, 10, 3) for _ in range(3)]
        self.run_objective(3, problems, 15, 0.8, 2.0, 12)

    def test_ring_low_noise(self):
        rng = np.random.default_rng(14)
        problems = [ring_problem(rng, 8, 0.02) for _ in range(2)]
        self.run_objective(4, problems, 18, 2.0, 1.0, 11)

    def test_ring_high_noise_hot(self):
        rng = np.random.default_rng(15)
        problems = [ring_problem(rng, 11, 0.3) for _ in range(2)]
        self.run_objective(5, problems, 22, 9.0, 1.2, 10)

    def test_tiny_problems(self):
        rng = np.random.default_rng(16)
        problems = [rng.random((5, 2)) for _ in range(4)]
        self.run_objective(6, problems, 12, 1.0, 2.0, 10)

    def test_long_patience_never_restarts(self):
        rng = np.random.default_rng(17)
        problems = [rng.random((10, 2)) for _ in range(2)]
        self.run_objective(7, problems, 25, 3.0, 2.5, 500)

    def test_grid_with_jitter(self):
        rng = np.random.default_rng(18)
        gx, gy = np.meshgrid(np.arange(4), np.arange(3))
        grid = np.stack([gx.ravel(), gy.ravel()], axis=-1) / 4.0
        problems = [grid + 0.01 * rng.standard_normal(grid.shape) for _ in range(2)]
        self.run_objective(8, problems, 20, 0.5, 4.0, 13)

    def test_collinear_scaled(self):
        rng = np.random.default_rng(19)
        problems = []
        for scale in (1.0, 3.0):
            xs = rng.permutation(np.linspace(0.0, scale, 7))
            problems.append(np.stack([xs, 0.1 * rng.random(7)], axis=-1))
        self.run_objective(9, problems, 16, 4.0, 1.0, 10)

    def test_mixed_sizes_shared_shape(self):
        rng = np.random.default_rng(20)
        problems = [clustered_problem(rng, 14, 2), rng.random((14, 2)), ring_problem(rng, 14, 0.1)]
        self.run_objective(10, problems, 14, 1.5, 6.0, 10)

    def test_warm_moderate_patience(self):
        rng = np.random.default_rng(21)
        problems = [rng.random((8, 2)) * np.array([2.0, 0.5]) for _ in range(3)]
        self.run_objective(11, problems, 21, 0.3, 1.0, 15)

    def test_single_large_problem(self):
        rng = np.random.default_rng(22)
        problems = [rng.random((16, 2))]
        self.run_objective(12, problems, 30, 6.0, 2.0, 10)


if __name__ == "__main__":
    unittest.main()
