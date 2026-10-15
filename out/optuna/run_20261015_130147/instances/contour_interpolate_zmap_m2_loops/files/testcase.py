from __future__ import annotations

import math
import unittest
from unittest import mock

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import optuna  # noqa: E402
from optuna.distributions import CategoricalDistribution  # noqa: E402
from optuna.distributions import FloatDistribution  # noqa: E402
from optuna.distributions import IntDistribution  # noqa: E402
from optuna.trial import create_trial  # noqa: E402
from optuna.visualization.matplotlib import _contour as mpl_contour  # noqa: E402
from optuna.visualization.matplotlib import plot_contour  # noqa: E402


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _build_study(specs, n_trials, seed, objective_fn, direction="minimize"):
    """Create a study by adding `n_trials` trials whose params come from a seeded RNG.

    `specs` maps a param name to (distribution, sampler-callable(rng, i) -> value or None).
    A sampler returning None means the param is absent from that trial.
    """
    rng = np.random.RandomState(seed)
    study = optuna.create_study(direction=direction)
    for i in range(n_trials):
        params = {}
        dists = {}
        for name in sorted(specs):
            dist, draw = specs[name]
            v = draw(rng, i)
            if v is None:
                continue
            params[name] = v
            dists[name] = dist
        study.add_trial(
            create_trial(value=float(objective_fn(params, i)), params=params, distributions=dists)
        )
    return study


def _plot(study, grid, params=None):
    with mock.patch.object(mpl_contour, "CONTOUR_POINT_NUM", grid):
        axs = plot_contour(study, params=params)
    plt.close("all")
    return axs


class TestMatplotlibContourInterpolation(unittest.TestCase):
    def test_two_floats_dense(self):
        study = _build_study(
            {
                "a": (FloatDistribution(-3.0, 3.0), lambda r, i: float(r.uniform(-3.0, 3.0))),
                "b": (FloatDistribution(0.0, 5.0), lambda r, i: float(r.uniform(0.0, 5.0))),
            },
            n_trials=40,
            seed=11,
            objective_fn=lambda p, i: p["a"] ** 2 + math.sin(p["b"]),
        )
        axs = _plot(study, 10)
        self.assertEqual(axs.get_xlabel(), "a")

    def test_two_floats_sparse_large_grid(self):
        study = _build_study(
            {
                "u": (FloatDistribution(0.0, 1.0), lambda r, i: float(r.rand())),
                "v": (FloatDistribution(0.0, 1.0), lambda r, i: float(r.rand())),
            },
            n_trials=6,
            seed=23,
            objective_fn=lambda p, i: p["u"] - p["v"],
        )
        axs = _plot(study, 14)
        self.assertEqual(axs.get_ylabel(), "v")

    def test_log_and_linear(self):
        study = _build_study(
            {
                "lr": (
                    FloatDistribution(1e-4, 1e-1, log=True),
                    lambda r, i: float(10 ** r.uniform(-4.0, -1.0)),
                ),
                "mom": (FloatDistribution(0.5, 0.99), lambda r, i: float(r.uniform(0.5, 0.99))),
            },
            n_trials=25,
            seed=5,
            objective_fn=lambda p, i: math.log10(p["lr"]) * p["mom"],
        )
        axs = _plot(study, 9)
        self.assertEqual(axs.get_xscale(), "log")

    def test_int_grid_collisions(self):
        study = _build_study(
            {
                "m": (IntDistribution(0, 4), lambda r, i: int(r.randint(0, 5))),
                "n": (IntDistribution(0, 3), lambda r, i: int(r.randint(0, 4))),
            },
            n_trials=30,
            seed=77,
            objective_fn=lambda p, i: p["m"] * 3 - p["n"] + 0.01 * i,
        )
        axs = _plot(study, 11)
        self.assertEqual(axs.get_xlabel(), "m")

    def test_categorical_vs_float(self):
        cats = ("adam", "sgd", "rmsprop")
        study = _build_study(
            {
                "opt": (CategoricalDistribution(cats), lambda r, i: cats[int(r.randint(0, 3))]),
                "wd": (FloatDistribution(0.0, 0.2), lambda r, i: float(r.uniform(0.0, 0.2))),
            },
            n_trials=18,
            seed=3,
            objective_fn=lambda p, i: cats.index(p["opt"]) + 10 * p["wd"],
        )
        axs = _plot(study, 8)
        self.assertEqual(len(axs.get_xticklabels()), len(cats))

    def test_three_params_grid(self):
        study = _build_study(
            {
                "x": (FloatDistribution(-1.0, 1.0), lambda r, i: float(r.uniform(-1.0, 1.0))),
                "y": (FloatDistribution(-2.0, 2.0), lambda r, i: float(r.uniform(-2.0, 2.0))),
                "z": (IntDistribution(1, 6), lambda r, i: int(r.randint(1, 7))),
            },
            n_trials=15,
            seed=41,
            objective_fn=lambda p, i: p["x"] * p["y"] + p["z"],
        )
        axs = _plot(study, 7)
        self.assertEqual(axs.shape, (3, 3))

    def test_conditional_missing_params(self):
        def draw_c(r, i):
            v = float(r.uniform(0.0, 10.0))
            return v if i % 3 != 0 else None

        study = _build_study(
            {
                "p": (FloatDistribution(0.0, 1.0), lambda r, i: float(r.rand())),
                "c": (FloatDistribution(0.0, 10.0), draw_c),
            },
            n_trials=21,
            seed=8,
            objective_fn=lambda p, i: p["p"] + p.get("c", 0.0),
        )
        axs = _plot(study, 12)
        self.assertEqual(axs.get_xlabel(), "c")

    def test_single_param_no_contour(self):
        study = _build_study(
            {"only": (FloatDistribution(0.0, 1.0), lambda r, i: float(r.rand()))},
            n_trials=10,
            seed=2,
            objective_fn=lambda p, i: p["only"],
        )
        axs = _plot(study, 10)
        self.assertEqual(len(axs.collections), 0)

    def test_constant_axis_skips_subplot(self):
        study = _build_study(
            {
                "fixed": (FloatDistribution(0.0, 1.0), lambda r, i: 0.5),
                "free": (FloatDistribution(0.0, 1.0), lambda r, i: float(r.rand())),
            },
            n_trials=12,
            seed=19,
            objective_fn=lambda p, i: p["free"],
        )
        axs = _plot(study, 10)
        self.assertEqual(len(axs.collections), 0)

    def test_two_categoricals_maximize(self):
        colors = ("red", "green", "blue", "cyan")
        sizes = ("s", "m", "l")
        study = _build_study(
            {
                "color": (
                    CategoricalDistribution(colors),
                    lambda r, i: colors[int(r.randint(0, 4))],
                ),
                "size": (CategoricalDistribution(sizes), lambda r, i: sizes[int(r.randint(0, 3))]),
            },
            n_trials=14,
            seed=29,
            objective_fn=lambda p, i: colors.index(p["color"]) * sizes.index(p["size"]),
            direction="maximize",
        )
        axs = _plot(study, 13)
        self.assertEqual(len(axs.get_yticklabels()), len(sizes))

    def test_four_params_subset(self):
        study = _build_study(
            {
                "k1": (FloatDistribution(0.0, 3.0), lambda r, i: float(r.uniform(0.0, 3.0))),
                "k2": (IntDistribution(0, 9), lambda r, i: int(r.randint(0, 10))),
                "k3": (
                    FloatDistribution(1.0, 100.0, log=True),
                    lambda r, i: float(10 ** r.uniform(0.0, 2.0)),
                ),
                "k4": (FloatDistribution(-5.0, 5.0), lambda r, i: float(r.uniform(-5.0, 5.0))),
            },
            n_trials=9,
            seed=101,
            objective_fn=lambda p, i: p["k1"] + p["k2"] - math.log(p["k3"]) + abs(p["k4"]),
        )
        axs = _plot(study, 6, params=["k1", "k3", "k4"])
        self.assertEqual(axs.shape, (3, 3))

    def test_target_override_wide_range(self):
        study = _build_study(
            {
                "alpha": (FloatDistribution(0.0, 100.0), lambda r, i: float(r.uniform(0, 100.0))),
                "beta": (IntDistribution(-20, 20), lambda r, i: int(r.randint(-20, 21))),
            },
            n_trials=50,
            seed=64,
            objective_fn=lambda p, i: p["alpha"] / (1 + abs(p["beta"])),
        )
        with mock.patch.object(mpl_contour, "CONTOUR_POINT_NUM", 15):
            axs = plot_contour(study, target=lambda t: t.params["alpha"] + t.params["beta"])
        plt.close("all")
        self.assertEqual(axs.get_xlabel(), "alpha")


if __name__ == "__main__":
    unittest.main()
