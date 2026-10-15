import random
import unittest

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.trial import create_trial
from optuna.trial import TrialState
from optuna.visualization import plot_contour


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _float_study(seed, n_trials, names, direction="minimize"):
    rng = random.Random(seed)
    study = optuna.create_study(direction=direction)
    dists = {n: FloatDistribution(-3.0, 3.0) for n in names}
    for _ in range(n_trials):
        params = {n: rng.uniform(-3.0, 3.0) for n in names}
        study.add_trial(
            create_trial(value=sum(v * v for v in params.values()), params=params,
                         distributions=dists)
        )
    return study


def _n_traces(fig):
    return len(fig.data)


class TestContourSubplots(unittest.TestCase):
    def test_three_float_params_all(self):
        study = _float_study(11, 17, ["alpha", "beta", "gamma"])
        fig = plot_contour(study)
        self.assertGreater(_n_traces(fig), 0)

    def test_categorical_grid_maximize_duplicates(self):
        rng = random.Random(7)
        study = optuna.create_study(direction="maximize")
        dists = {
            "color": CategoricalDistribution(["red", "green", "blue"]),
            "size": IntDistribution(1, 4),
        }
        for k in range(23):
            params = {"color": rng.choice(["red", "green", "blue"]), "size": rng.randint(1, 4)}
            value = float((k * 7) % 13) - rng.random()
            study.add_trial(create_trial(value=value, params=params, distributions=dists))
        fig = plot_contour(study)
        self.assertGreater(_n_traces(fig), 0)

    def test_conditional_missing_params(self):
        rng = random.Random(101)
        study = optuna.create_study()
        for k in range(19):
            params = {"base": rng.uniform(0.0, 10.0)}
            dists = {"base": FloatDistribution(0.0, 10.0)}
            if k % 3 != 0:
                params["extra"] = rng.uniform(0.0, 1.0)
                dists["extra"] = FloatDistribution(0.0, 1.0)
            study.add_trial(create_trial(value=params["base"] - k, params=params,
                                         distributions=dists))
        fig = plot_contour(study, params=["base", "extra"])
        self.assertGreater(_n_traces(fig), 0)

    def test_custom_target_with_repeated_grid(self):
        rng = random.Random(55)
        study = optuna.create_study()
        dists = {"p": IntDistribution(0, 2), "q": IntDistribution(0, 2)}
        for _ in range(16):
            params = {"p": rng.randint(0, 2), "q": rng.randint(0, 2)}
            study.add_trial(create_trial(value=rng.random(), params=params, distributions=dists))
        fig = plot_contour(study, target=lambda t: t.params["p"] * 2.0 - t.value)
        self.assertGreater(_n_traces(fig), 0)

    def test_minimize_int_grid_duplicates(self):
        rng = random.Random(64)
        study = optuna.create_study(direction="minimize")
        dists = {"depth": IntDistribution(1, 3), "width": IntDistribution(1, 2)}
        for k in range(21):
            params = {"depth": rng.randint(1, 3), "width": rng.randint(1, 2)}
            value = (k % 5) * 0.5 + rng.random()
            study.add_trial(create_trial(value=value, params=params, distributions=dists))
        fig = plot_contour(study)
        self.assertGreater(_n_traces(fig), 0)

    def test_constant_y_param(self):
        rng = random.Random(4)
        study = optuna.create_study()
        dists = {"aa": FloatDistribution(0.0, 5.0), "zz": FloatDistribution(0.0, 5.0)}
        for _ in range(9):
            params = {"aa": rng.uniform(0.0, 5.0), "zz": 1.0}
            study.add_trial(create_trial(value=rng.random(), params=params, distributions=dists))
        fig = plot_contour(study)
        self.assertIsNotNone(fig.layout)

    def test_log_scale_and_subset_of_four(self):
        rng = random.Random(29)
        study = optuna.create_study(direction="maximize")
        dists = {
            "lr": FloatDistribution(1e-5, 1e-1, log=True),
            "units": IntDistribution(8, 128, log=True),
            "drop": FloatDistribution(0.0, 0.5),
            "act": CategoricalDistribution(["relu", "tanh"]),
        }
        for _ in range(14):
            params = {
                "lr": 10 ** rng.uniform(-5, -1),
                "units": rng.choice([8, 16, 32, 64, 128]),
                "drop": rng.uniform(0.0, 0.5),
                "act": rng.choice(["relu", "tanh"]),
            }
            study.add_trial(create_trial(value=rng.random(), params=params, distributions=dists))
        fig = plot_contour(study, params=["units", "lr", "act"])
        self.assertGreater(_n_traces(fig), 0)

    def test_duplicate_param_name_only(self):
        study = _float_study(42, 6, ["solo", "other"])
        fig = plot_contour(study, params=["solo", "solo"])
        self.assertIsNotNone(fig)

    def test_failed_and_pruned_trials_filtered(self):
        rng = random.Random(77)
        study = optuna.create_study()
        dists = {"u": IntDistribution(0, 3), "v": IntDistribution(0, 3)}
        for k in range(26):
            params = {"u": rng.randint(0, 3), "v": rng.randint(0, 3)}
            if k % 4 == 1:
                study.add_trial(create_trial(state=TrialState.FAIL, params=params,
                                             distributions=dists))
            elif k % 4 == 2:
                study.add_trial(create_trial(state=TrialState.PRUNED, params=params,
                                             distributions=dists))
            else:
                study.add_trial(create_trial(value=rng.uniform(-1, 1), params=params,
                                             distributions=dists))
        fig = plot_contour(study)
        self.assertGreater(_n_traces(fig), 0)

    def test_multi_objective_with_target(self):
        rng = random.Random(13)
        study = optuna.create_study(directions=["minimize", "maximize"])
        dists = {"m": FloatDistribution(0.0, 1.0), "n": CategoricalDistribution([1, 2, 3])}
        for _ in range(11):
            params = {"m": rng.random(), "n": rng.choice([1, 2, 3])}
            study.add_trial(create_trial(values=[rng.random(), rng.random()], params=params,
                                         distributions=dists))
        fig = plot_contour(study, target=lambda t: t.values[0] + t.values[1])
        self.assertGreater(_n_traces(fig), 0)

    def test_constraints_and_sparse_third_param(self):
        rng = random.Random(91)
        study = optuna.create_study()
        for k in range(15):
            params = {"c1": rng.randint(0, 5), "c2": rng.uniform(0.0, 1.0)}
            dists = {"c1": IntDistribution(0, 5), "c2": FloatDistribution(0.0, 1.0)}
            if k % 5 == 0:
                params["c3"] = rng.choice(["x", "y"])
                dists["c3"] = CategoricalDistribution(["x", "y"])
            study.add_trial(
                create_trial(
                    value=rng.random(),
                    params=params,
                    distributions=dists,
                    system_attrs={"constraints": [rng.uniform(-1.0, 1.0)]},
                )
            )
        fig = plot_contour(study)
        self.assertGreater(_n_traces(fig), 0)

    def test_no_completed_trials(self):
        study = optuna.create_study()
        study.add_trial(
            create_trial(state=TrialState.FAIL, params={"a": 1.0},
                         distributions={"a": FloatDistribution(0.0, 2.0)})
        )
        fig = plot_contour(study)
        self.assertEqual(len(fig.data), 0)
