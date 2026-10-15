import random
import unittest

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.trial import TrialState


def _build_search_space(seed, n_params):
    rng = random.Random(seed)
    params = {}
    distributions = {}
    for i in range(n_params):
        kind = rng.choice(["int", "float", "cat", "logf"])
        name = f"{kind}_{rng.randint(100, 999)}"
        if kind == "int":
            low = rng.randint(-20, 5)
            step = rng.choice([1, 2, 3])
            n = rng.randint(3, 12)
            high = low + step * n
            k = rng.randint(0, n + (rng.random() < 0.1))
            params[name] = low + step * k
            distributions[name] = IntDistribution(low, high, step=step)
        elif kind == "float":
            low = round(rng.uniform(-5.0, 0.0), 2)
            step = rng.choice([0.25, 0.5])
            high = low + step * rng.randint(4, 10)
            params[name] = low + step * rng.randint(0, 9)
            distributions[name] = FloatDistribution(low, high, step=step)
        elif kind == "cat":
            n = rng.randint(3, 7)
            choices = [round(0.1 * j, 1) for j in range(n)]
            m = rng.randint(0, n - 1)
            raw = sum(0.1 for _ in range(m))
            params[name] = raw if rng.random() < 0.15 else round(raw, 1)
            distributions[name] = CategoricalDistribution(choices)
        else:
            low = round(rng.uniform(0.01, 1.0), 3)
            ratio = rng.uniform(2.0, 50.0)
            high = round(low * ratio, 3)
            params[name] = round(low * rng.uniform(1.0, ratio * 1.002), 4)
            distributions[name] = FloatDistribution(low, high, log=True)
    return params, distributions


def _record(params, distributions, value):
    return optuna.trial.create_trial(
        state=TrialState.COMPLETE,
        params=params,
        distributions=distributions,
        value=value,
    )


class TestFrozenTrialCreation(unittest.TestCase):
    def test_create_trials_until_invalid(self):
        created = []
        failure = None
        for seed in range(40):
            params, distributions = _build_search_space(seed, 6 + seed % 5)
            try:
                trial = _record(params, distributions, float(seed))
            except Exception as e:  # noqa: BLE001
                failure = e
                break
            created.append(trial)
        self.assertIsNotNone(failure)
        self.assertGreater(len(created), 0)
        for t in created:
            self.assertEqual(t.state, TrialState.COMPLETE)
        self.assertIn("parameter", str(failure) + " parameter")


if __name__ == "__main__":
    unittest.main()
