from __future__ import annotations

import math
import random
import unittest
import warnings

from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.study import StudyDirection
from optuna.terminator.improvement.emmr import EMMREvaluator
from optuna.trial import create_trial
from optuna.trial import FrozenTrial
from optuna.trial import TrialState


MODES = ("lin", "quad", "cube")


def _build_trials(seed: int, n: int) -> list[FrozenTrial]:
    rng = random.Random(seed)
    base = {
        "alpha": FloatDistribution(-5.0, 5.0),
        "beta": FloatDistribution(1e-3, 10.0, log=True),
        "gamma": IntDistribution(2, 40, step=2),
        "mode": CategoricalDistribution(MODES),
    }
    trials = []
    for i in range(n):
        params = {
            "alpha": rng.uniform(-5.0, 5.0),
            "beta": math.exp(rng.uniform(math.log(1e-3), math.log(10.0))),
            "gamma": 2 * rng.randint(1, 20),
            "mode": rng.choice(MODES),
        }
        dists = dict(base)
        if i % 3 != 1:
            # Only some trials carry this parameter.
            params["extra"] = rng.random()
            dists["extra"] = FloatDistribution(0.0, 1.0)
        power = MODES.index(params["mode"]) + 1
        value = (params["alpha"] - 1.5) ** power * 0.3 + math.log10(params["beta"]) ** 2
        value += (params["gamma"] - 18) / 7.0
        if i == 2 * (n // 3) + 1:
            value = math.inf
        if i % 5 == 4:
            state = TrialState.PRUNED
            value = None
        else:
            state = TrialState.COMPLETE
        trials.append(
            create_trial(state=state, value=value, params=params, distributions=dists)
        )
    return trials


class TestEMMREvaluateState(unittest.TestCase):
    def test_evaluate_over_growing_histories(self) -> None:
        trials = _build_trials(seed=731, n=19)
        no_param_trials = [create_trial(value=float(k * k - 3)) for k in range(4)]
        evaluator = EMMREvaluator(seed=11, min_n_trials=3)

        plan = [
            (trials[:2], StudyDirection.MINIMIZE),
            (no_param_trials, StudyDirection.MAXIMIZE),
            (trials[:9], StudyDirection.MINIMIZE),
            (trials[:16], StudyDirection.MAXIMIZE),
            (trials, StudyDirection.MINIMIZE),
        ]
        results = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for ts, direction in plan:
                results.append(evaluator.evaluate(ts, direction))

        self.assertEqual(len(results), len(plan))
        for r in results:
            self.assertTrue(math.isfinite(r))
        self.assertEqual(results[0], results[1])
        for r in results[2:]:
            self.assertLess(r, results[0])


if __name__ == "__main__":
    unittest.main()
