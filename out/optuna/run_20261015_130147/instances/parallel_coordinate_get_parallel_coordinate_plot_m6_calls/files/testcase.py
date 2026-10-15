from __future__ import annotations

import math
import random
import unittest

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.trial import create_trial
from optuna.trial import TrialState
from optuna.visualization import plot_parallel_coordinate


optuna.logging.set_verbosity(optuna.logging.ERROR)


FX = FloatDistribution(-5.0, 5.0)
FLR = FloatDistribution(1e-5, 1e-1, log=True)
IDEPTH = IntDistribution(1, 12)
CCOLOR = CategoricalDistribution(["red", "green", "blue", "cyan"])
CUNITS = CategoricalDistribution([16, 32, 64, 128])


def _add_trials(study, n, seed, builder, state_every=0):
    rng = random.Random(seed)
    for i in range(n):
        params, dists, value = builder(rng, i)
        if state_every and i % state_every == state_every - 1:
            study.add_trial(
                create_trial(state=TrialState.FAIL, params=params, distributions=dists)
            )
            continue
        if isinstance(value, (list, tuple)):
            study.add_trial(create_trial(values=list(value), params=params, distributions=dists))
        else:
            study.add_trial(create_trial(value=value, params=params, distributions=dists))


def _mixed_builder(rng, i):
    x = round(rng.uniform(-5.0, 5.0), 3)
    lr = 10 ** rng.uniform(-5.0, -1.0)
    params = {"x": x, "lr": lr}
    dists = {"x": FX, "lr": FLR}
    if i % 3 != 1:
        params["depth"] = rng.randint(1, 12)
        dists["depth"] = IDEPTH
    return params, dists, x * x + math.log10(lr)


class TestParallelCoordinateCallGraph(unittest.TestCase):
    def test_empty_study(self) -> None:
        study = optuna.create_study()
        figure = plot_parallel_coordinate(study)
        self.assertEqual(len(figure.data), 0)

    def test_mixed_numeric_and_log_with_missing(self) -> None:
        study = optuna.create_study()
        _add_trials(study, 17, 3, _mixed_builder)
        figure = plot_parallel_coordinate(study)
        self.assertGreater(len(figure.data), 1)
        self.assertEqual(figure.data[0].line.dash, "solid")

    def test_multi_objective_rank_colors(self) -> None:
        study = optuna.create_study(directions=["minimize", "maximize", "minimize"])

        def builder(rng, i):
            a = rng.uniform(0.0, 1.0)
            b = rng.uniform(0.0, 1.0)
            return (
                {"a": a, "b": b},
                {"a": FloatDistribution(0.0, 1.0), "b": FloatDistribution(0.0, 1.0)},
                (a + b, a - b * b, (1 - a) ** 2 + b),
            )

        _add_trials(study, 13, 11, builder)
        figure = plot_parallel_coordinate(study)
        self.assertTrue(figure.data[-1].marker.showscale)

    def test_categorical_numeric_and_string(self) -> None:
        study = optuna.create_study(direction="maximize")

        def builder(rng, i):
            units = rng.choice([16, 32, 64, 128])
            color = rng.choice(["red", "green", "blue", "cyan"])
            params = {"units": units, "x": rng.uniform(-5.0, 5.0)}
            dists = {"units": CUNITS, "x": FX}
            if i % 4 != 0:
                params["color"] = color
                dists["color"] = CCOLOR
            return params, dists, units / 128.0 + len(color) * 0.1

        _add_trials(study, 19, 5, builder)
        figure = plot_parallel_coordinate(study)
        self.assertGreater(len(figure.layout.annotations), 0)

    def test_unknown_param_raises(self) -> None:
        study = optuna.create_study()
        _add_trials(study, 6, 21, _mixed_builder)
        with self.assertRaises(ValueError):
            plot_parallel_coordinate(study, params=["x", "does_not_exist"])

    def test_trials_without_params(self) -> None:
        study = optuna.create_study()
        for k in range(7):
            study.add_trial(create_trial(value=float(k * k - 3)))
        figure = plot_parallel_coordinate(study)
        self.assertEqual(len(figure.data), 0)

    def test_custom_target_filters_nonfinite(self) -> None:
        study = optuna.create_study()
        _add_trials(study, 14, 8, _mixed_builder)

        def target(t):
            if t.number % 5 == 2:
                return float("nan")
            return t.params["x"] * 2.0

        figure = plot_parallel_coordinate(study, target=target, target_name="Twice X")
        self.assertIn("Twice", figure.layout.xaxis.ticktext[0])

    def test_long_names_and_subset(self) -> None:
        study = optuna.create_study()

        def builder(rng, i):
            params = {
                "a_really_long_parameter_name_alpha": rng.uniform(-5.0, 5.0),
                "short": rng.randint(1, 12),
                "another_quite_long_parameter_beta": 10 ** rng.uniform(-5.0, -1.0),
            }
            dists = {
                "a_really_long_parameter_name_alpha": FX,
                "short": IDEPTH,
                "another_quite_long_parameter_beta": FLR,
            }
            return params, dists, sum(float(v) for v in params.values())

        _add_trials(study, 11, 17, builder, state_every=4)
        figure = plot_parallel_coordinate(
            study, params=["a_really_long_parameter_name_alpha", "short"]
        )
        self.assertTrue(any(text.endswith("...") for text in figure.layout.xaxis.ticktext))

    def test_single_trial_constant_ranges(self) -> None:
        study = optuna.create_study()
        study.add_trial(
            create_trial(
                value=1.5,
                params={"x": 0.25, "lr": 1e-3, "color": "blue"},
                distributions={"x": FX, "lr": FLR, "color": CCOLOR},
            )
        )
        figure = plot_parallel_coordinate(study)
        self.assertGreater(len(figure.data), 1)

    def test_multi_objective_all_nonfinite(self) -> None:
        study = optuna.create_study(directions=["minimize", "minimize"])

        def builder(rng, i):
            x = rng.uniform(-5.0, 5.0)
            return {"x": x}, {"x": FX}, (x, float("inf") if i % 2 else float("-inf"))

        _add_trials(study, 5, 2, builder)
        figure = plot_parallel_coordinate(study)
        self.assertEqual(len(figure.data), 0)

    def test_multi_objective_with_target_and_failed_trials(self) -> None:
        study = optuna.create_study(directions=["minimize", "maximize"])

        def builder(rng, i):
            depth = rng.randint(1, 12)
            units = rng.choice([16, 32, 64, 128])
            params = {"depth": depth}
            dists = {"depth": IDEPTH}
            if i % 2 == 0:
                params["units"] = units
                dists["units"] = CUNITS
            return params, dists, (depth * 0.5, units / 16.0)

        _add_trials(study, 16, 29, builder, state_every=5)
        figure = plot_parallel_coordinate(
            study, target=lambda t: t.values[0] - t.values[1], target_name="Gap"
        )
        self.assertGreater(len(figure.data), 2)

    def test_two_plots_from_one_study(self) -> None:
        study = optuna.create_study()
        _add_trials(study, 9, 41, _mixed_builder)
        whole = plot_parallel_coordinate(study)
        only_lr = plot_parallel_coordinate(study, params=["lr"])
        self.assertGreater(len(whole.layout.annotations), len(only_lr.layout.annotations))


if __name__ == "__main__":
    unittest.main()
