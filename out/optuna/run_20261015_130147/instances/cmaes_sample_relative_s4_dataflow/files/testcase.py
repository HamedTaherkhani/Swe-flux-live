import math
import unittest
import warnings

import numpy as np

import optuna
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.samplers import CmaEsSampler
from optuna.trial import TrialState


def _objective(params, rng):
    total = 0.0
    for idx, name in enumerate(sorted(params)):
        total += (idx + 1) * (float(params[name]) - 0.5 * idx) ** 2
    return total + float(rng.uniform(0.0, 0.01))


def _random_params(space, rng):
    out = {}
    for name, dist in space.items():
        if isinstance(dist, IntDistribution):
            out[name] = int(rng.integers(dist.low, dist.high + 1))
        elif dist.log:
            out[name] = float(math.exp(rng.uniform(math.log(dist.low), math.log(dist.high))))
        else:
            out[name] = float(rng.uniform(dist.low, dist.high))
    return out


def _drive(sampler, study, base_space, n_calls, rng, empty_at, extra_at, fail_every):
    storage = study._storage
    extended = dict(base_space)
    extended["extra"] = FloatDistribution(-1.0, 1.0)
    sampled_by_cma = 0
    for i in range(n_calls):
        trial_id = storage.create_new_trial(study._study_id)
        frozen = storage.get_trial(trial_id)
        if i in empty_at:
            space = {}
        elif i in extra_at:
            space = extended
        else:
            space = base_space
        study._thread_local.cached_all_trials = None
        params = sampler.sample_relative(study, frozen, space)
        if params:
            sampled_by_cma += 1
            used_space = space
        else:
            used_space = base_space
            params = _random_params(base_space, rng)
        for name, dist in used_space.items():
            if name not in params:
                params[name] = _random_params({name: dist}, rng)[name]
            storage.set_trial_param(trial_id, name, dist.to_internal_repr(params[name]), dist)
        if fail_every and i % fail_every == fail_every - 1:
            storage.set_trial_state_values(trial_id, TrialState.FAIL)
        else:
            storage.set_trial_state_values(
                trial_id, TrialState.COMPLETE, [_objective(params, rng)]
            )
    return sampled_by_cma


class TestCmaEsSampleRelativeDataFlow(unittest.TestCase):
    def test_sample_relative_two_samplers(self):
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        rng = np.random.default_rng(20240607)

        space_a = {
            "a": FloatDistribution(-3.0, 3.0),
            "b": FloatDistribution(1e-3, 10.0, log=True),
            "c": FloatDistribution(0.0, 2.0),
        }
        sampler_a = CmaEsSampler(seed=11, n_startup_trials=3, popsize=4)
        study_a = optuna.create_study(sampler=sampler_a, direction="minimize")
        n_a = _drive(
            sampler_a,
            study_a,
            space_a,
            n_calls=int(rng.integers(20, 23)),
            rng=rng,
            empty_at={1, int(rng.integers(9, 12))},
            extra_at={int(rng.integers(13, 15))},
            fail_every=7,
        )

        space_b = {
            "p": IntDistribution(0, 8),
            "q": IntDistribution(-4, 4, step=2),
            "r": FloatDistribution(-1.0, 1.0),
        }
        sampler_b = CmaEsSampler(seed=5, n_startup_trials=2, popsize=3, with_margin=True)
        study_b = optuna.create_study(sampler=sampler_b, direction="maximize")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            n_b = _drive(
                sampler_b,
                study_b,
                space_b,
                n_calls=int(rng.integers(12, 15)),
                rng=rng,
                empty_at=set(),
                extra_at={int(rng.integers(8, 11))},
                fail_every=5,
            )

        self.assertGreater(n_a, 5)
        self.assertGreater(n_b, 3)
        self.assertFalse(sampler_a._warn_independent_sampling)
        self.assertFalse(sampler_b._warn_independent_sampling)
        completed = [t for t in study_a.trials if t.state == TrialState.COMPLETE]
        self.assertTrue(all(np.isfinite(t.value) for t in completed))


if __name__ == "__main__":
    unittest.main()
