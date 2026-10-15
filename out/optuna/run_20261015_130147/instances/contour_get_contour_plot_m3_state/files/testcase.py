import math
import unittest
import warnings

import optuna
from optuna.visualization import plot_contour


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _run(seed, n_trials, objective, directions=None):
    sampler = optuna.samplers.RandomSampler(seed=seed)
    if directions is None:
        study = optuna.create_study(sampler=sampler)
    else:
        study = optuna.create_study(directions=directions, sampler=sampler)
    study.optimize(objective, n_trials=n_trials)
    return study


def _plot(study, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return plot_contour(study, **kwargs)


class TestContourLogRanges(unittest.TestCase):
    def test_two_log_params(self):
        def objective(trial):
            lr = trial.suggest_float("lr", 1e-5, 1e-1, log=True)
            wd = trial.suggest_float("wd", 1e-6, 1e-2, log=True)
            return math.log10(lr) ** 2 + math.log10(wd)

        study = _run(11, 17, objective)
        fig = _plot(study)
        self.assertEqual(fig.layout.xaxis.type, "log")
        self.assertEqual(fig.layout.yaxis.type, "log")
        self.assertEqual(len(fig.data), 3)

    def test_log_x_linear_y(self):
        def objective(trial):
            alpha = trial.suggest_float("alpha", 0.002, 30.0, log=True)
            beta = trial.suggest_float("beta", -4.0, 4.0)
            return alpha * beta

        study = _run(23, 19, objective)
        fig = _plot(study)
        self.assertEqual(fig.layout.xaxis.type, "log")
        self.assertIsNone(fig.layout.yaxis.type)

    def test_linear_x_log_int_y(self):
        def objective(trial):
            a = trial.suggest_float("a", 0.0, 10.0)
            units = trial.suggest_int("units", 4, 700, log=True)
            return a - math.sqrt(units)

        study = _run(37, 21, objective)
        fig = _plot(study)
        self.assertIsNone(fig.layout.xaxis.type)
        self.assertEqual(fig.layout.yaxis.type, "log")

    def test_three_params_log_int_cat(self):
        def objective(trial):
            c = trial.suggest_float("c", 0.05, 500.0, log=True)
            depth = trial.suggest_int("depth", 1, 12)
            kind = trial.suggest_categorical("kind", ["rbf", "poly", "lin"])
            return c / depth + (1.0 if kind == "rbf" else 0.0)

        study = _run(41, 23, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 3 + 6 * 2)

    def test_four_params_two_log(self):
        def objective(trial):
            p = trial.suggest_float("p", 3e-4, 0.9, log=True)
            q = trial.suggest_int("q", 2, 4096, log=True)
            r = trial.suggest_float("r", -1.0, 1.0)
            s = trial.suggest_categorical("s", ["u", "v"])
            return p * q + r + (0.5 if s == "u" else -0.5)

        study = _run(53, 26, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 4 + 12 * 2)

    def test_param_subset(self):
        def objective(trial):
            eta = trial.suggest_float("eta", 1e-3, 2.0, log=True)
            gamma = trial.suggest_float("gamma", 0.1, 50.0, log=True)
            mu = trial.suggest_float("mu", 0.0, 1.0)
            return eta + gamma * mu

        study = _run(67, 18, objective)
        fig = _plot(study, params=["gamma", "mu"])
        self.assertEqual(fig.layout.xaxis.type, "log")
        self.assertEqual(fig.layout.xaxis.title.text, "gamma")

    def test_single_param_early_return(self):
        def objective(trial):
            return trial.suggest_float("only", 1e-3, 1e3, log=True)

        study = _run(71, 15, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 0)

    def test_conditional_log_params(self):
        def objective(trial):
            branch = trial.suggest_categorical("branch", ["left", "right"])
            if branch == "left":
                k = trial.suggest_float("k_left", 0.01, 80.0, log=True)
            else:
                k = trial.suggest_float("k_right", 5e-4, 0.3, log=True)
            m = trial.suggest_float("m", 1e-2, 1e2, log=True)
            return k * m

        study = _run(83, 30, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 4 + 12 * 2)

    def test_multi_objective_with_target(self):
        def objective(trial):
            x = trial.suggest_float("x", 1e-2, 1e2, log=True)
            y = trial.suggest_float("y", 1e-3, 10.0, log=True)
            z = trial.suggest_int("z", 0, 9)
            return x + y, x * y - z

        study = _run(97, 22, objective, directions=["minimize", "maximize"])
        fig = _plot(study, target=lambda t: t.values[0] - t.values[1], target_name="diff")
        self.assertEqual(len(fig.data), 3 + 6 * 2)

    def test_log_int_pair_maximize(self):
        def objective(trial):
            batch = trial.suggest_int("batch", 8, 1024, log=True)
            epochs = trial.suggest_int("epochs", 1, 300, log=True)
            return math.log(batch) * math.log1p(epochs)

        sampler = optuna.samplers.RandomSampler(seed=109)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=20)
        fig = _plot(study)
        self.assertEqual(fig.layout.xaxis.title.text, "batch")
        self.assertEqual(len(fig.data), 3)

    def test_five_params_three_log(self):
        def objective(trial):
            f1 = trial.suggest_float("f1", 1e-4, 1.0, log=True)
            f2 = trial.suggest_float("f2", 0.5, 2000.0, log=True)
            f3 = trial.suggest_int("f3", 3, 999, log=True)
            g = trial.suggest_float("g", -10.0, 10.0)
            h = trial.suggest_categorical("h", ["a", "b", "c", "d"])
            return f1 * f2 / f3 + g + len(h)

        study = _run(127, 24, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 5 + 20 * 2)

    def test_three_params_derived_from_prior_study(self):
        def first(trial):
            return trial.suggest_float("seed_val", 1e-3, 1e3, log=True)

        pilot = _run(131, 12, first)
        lo = min(t.params["seed_val"] for t in pilot.trials)
        hi = max(t.params["seed_val"] for t in pilot.trials)

        def objective(trial):
            u = trial.suggest_float("u", lo, hi, log=True)
            v = trial.suggest_float("v", lo / 10.0, hi * 10.0, log=True)
            w = trial.suggest_int("w", 0, 5)
            return u - v + w

        study = _run(137, 25, objective)
        fig = _plot(study)
        self.assertEqual(len(fig.data), 3 + 6 * 2)


if __name__ == "__main__":
    unittest.main()
