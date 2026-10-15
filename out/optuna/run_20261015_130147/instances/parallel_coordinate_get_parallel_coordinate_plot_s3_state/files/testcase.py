import unittest
import warnings

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

import optuna  # noqa: E402
from optuna.visualization.matplotlib import plot_parallel_coordinate  # noqa: E402


def _objective(trial):
    x = trial.suggest_float("x", -3.0, 5.0)
    lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
    depth = trial.suggest_int("depth", 1, 9)
    mode = trial.suggest_categorical("mode", ["fixed"])
    kind = trial.suggest_categorical("kind", ["alpha", "beta", "gamma"])
    loss = (x - 1.0) ** 2 + depth * 0.3 + (0.5 if kind == "beta" else 0.0)
    gain = depth * 1.7 - abs(x) + (2.0 if mode == "fixed" and kind != "gamma" else -1.0)
    if kind == "gamma":
        gain += lr * 40.0
    return round(loss, 3), round(gain, 3)


class TestParallelCoordinateMultiObjective(unittest.TestCase):
    def test_plot_multi_objective_study(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        sampler = optuna.samplers.RandomSampler(seed=20240611)
        study = optuna.create_study(directions=["minimize", "maximize"], sampler=sampler)
        study.optimize(_objective, n_trials=18)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ax = plot_parallel_coordinate(study)

        self.assertEqual(len(ax.collections), 1)
        self.assertEqual(len(ax.collections[0].get_segments()), len(study.trials))
        self.assertEqual(len(ax.get_xticklabels()), 7)
        plt.close("all")


if __name__ == "__main__":
    unittest.main()
