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


def _single_objective_study(rng):
    study = optuna.create_study(direction="maximize")
    dists = {
        "alpha": FloatDistribution(0.0, 10.0),
        "kind": CategoricalDistribution(["x", "y", "z"]),
    }
    for i in range(6):
        params = {"alpha": round(rng.uniform(0.0, 10.0), 2)}
        if i % 2:
            params["kind"] = rng.choice(["x", "y", "z"])
        study.add_trial(
            create_trial(
                value=rng.uniform(-1.0, 1.0),
                params=params,
                distributions={k: dists[k] for k in params},
            )
        )
    return study


def _multi_objective_study(rng):
    study = optuna.create_study(directions=["minimize", "maximize"])
    dists = {
        "learning_rate": FloatDistribution(1e-4, 1.0, log=True),
        "batch": CategoricalDistribution([16, 32, 64, 128]),
        "optimizer": CategoricalDistribution(["adam", "sgd", "rmsprop", "None"]),
        "dropout": FloatDistribution(0.0, 0.5),
        "layers": IntDistribution(1, 8),
    }
    for i in range(14):
        params = {}
        if rng.random() < 0.8:
            params["learning_rate"] = 10 ** rng.uniform(-3.7, -0.3)
        params["batch"] = rng.choice([16, 32, 64, 128])
        if i % 3 != 1:
            params["optimizer"] = rng.choice(["adam", "sgd", "rmsprop", "None"])
        params["dropout"] = round(rng.uniform(0.0, 0.5), 3)
        if rng.random() < 0.7:
            params["layers"] = rng.randint(1, 8)
        values = [rng.uniform(0.0, 5.0), rng.uniform(0.0, 5.0)]
        if i % 5 == 4:
            values[i % 2] = float("inf")
        constraints = {"c0": rng.uniform(-1.0, 1.0)} if i % 4 else None
        study.add_trial(
            create_trial(
                values=values,
                params=params,
                distributions={k: dists[k] for k in params},
                constraints=constraints,
            )
        )
    study.add_trial(create_trial(state=TrialState.FAIL))
    return study


class TestParallelCoordinateFlow(unittest.TestCase):
    def test_three_plots(self):
        rng = random.Random(20261015)
        single = _single_objective_study(rng)
        multi = _multi_objective_study(rng)

        fig1 = plot_parallel_coordinate(single, target=lambda t: t.value * 2.0, target_name="Twice")
        fig2 = plot_parallel_coordinate(multi)
        fig3 = plot_parallel_coordinate(single, params=["alpha"])

        self.assertGreater(len(fig1.data), 1)
        self.assertGreater(len(fig2.data), 1)
        self.assertGreater(len(fig3.data), 1)
        self.assertEqual(fig2.layout.xaxis.ticktext[0], "Objective 0")


if __name__ == "__main__":
    unittest.main()
