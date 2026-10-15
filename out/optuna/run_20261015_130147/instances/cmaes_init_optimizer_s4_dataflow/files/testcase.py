import random
import unittest
import warnings

import cmaes
import numpy as np

import optuna
from optuna._transform import _SearchSpaceTransform
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.samplers import CmaEsSampler
from optuna.study import StudyDirection
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _make_space(rng, n_dim, prefix):
    space = {}
    for k in range(n_dim):
        flavor = rng.randrange(5)
        name = f"{prefix}{k}"
        if flavor == 0:
            space[name] = FloatDistribution(-rng.randint(1, 4), rng.randint(1, 6))
        elif flavor == 1:
            space[name] = FloatDistribution(10.0 ** -rng.randint(1, 3), 10.0 ** rng.randint(0, 2), log=True)
        elif flavor == 2:
            lo = rng.randint(-3, 2)
            space[name] = IntDistribution(lo, lo + rng.randint(2, 9))
        elif flavor == 3:
            lo = rng.randint(0, 4)
            space[name] = FloatDistribution(lo, lo + 2.0, step=0.25 * rng.randint(1, 3))
        else:
            v = rng.randint(1, 3)
            space[name] = IntDistribution(v, v)
    return space


def _sample_params(rng, space):
    params = {}
    for name, d in space.items():
        if isinstance(d, IntDistribution):
            params[name] = rng.randint(d.low, d.high)
        elif d.step is not None:
            n = int(round((d.high - d.low) / d.step))
            params[name] = d.low + d.step * rng.randint(0, n)
        elif d.log:
            params[name] = float(np.exp(rng.uniform(np.log(d.low), np.log(d.high))))
        else:
            params[name] = rng.uniform(d.low, d.high)
    return params


def _make_source_trials(rng, space, n_good, n_pruned, n_foreign):
    trials = []
    for _ in range(n_good):
        trials.append(
            optuna.trial.create_trial(
                params=_sample_params(rng, space),
                distributions=space,
                value=rng.uniform(-5.0, 5.0),
            )
        )
    for _ in range(n_pruned):
        trials.append(
            optuna.trial.create_trial(
                state=TrialState.PRUNED,
                params=_sample_params(rng, space),
                distributions=space,
                value=rng.uniform(-5.0, 5.0),
            )
        )
    foreign = {"zz_" + k: v for k, v in space.items()}
    for _ in range(n_foreign):
        trials.append(
            optuna.trial.create_trial(
                params=_sample_params(rng, foreign),
                distributions=foreign,
                value=rng.uniform(-5.0, 5.0),
            )
        )
    rng.shuffle(trials)
    return trials


KINDS = ["plain", "x0_sigma", "sep", "sep_1d_x0", "margin", "warm", "warm_margin", "no_compat"]


class TestCmaEsInitOptimizerDataFlow(unittest.TestCase):
    def test_init_optimizer_many_configs(self):
        rng = random.Random(4242)
        outcomes = []
        for idx in range(20):
            kind = KINDS[(idx * 5 + rng.randrange(3)) % len(KINDS)]
            direction = StudyDirection.MINIMIZE if rng.random() < 0.5 else StudyDirection.MAXIMIZE
            n_dim = 1 if kind == "sep_1d_x0" else rng.randint(2, 5)
            space = _make_space(rng, n_dim, f"p{idx}_")
            kwargs = {"seed": idx}
            if kind == "x0_sigma" or kind == "sep_1d_x0":
                kwargs["x0"] = _sample_params(rng, space)
                kwargs["sigma0"] = rng.choice([1e-30, 0.2, 0.05])
            if kind in ("sep", "sep_1d_x0"):
                kwargs["use_separable_cma"] = True
            if kind in ("margin", "warm_margin"):
                kwargs["with_margin"] = True
            if kind in ("warm", "warm_margin"):
                kwargs["consider_pruned_trials"] = rng.random() < 0.5
                kwargs["source_trials"] = _make_source_trials(
                    rng, space, rng.randint(8, 14), rng.randint(2, 6), rng.randint(0, 3)
                )
            if kind == "no_compat":
                kwargs["consider_pruned_trials"] = False
                kwargs["source_trials"] = _make_source_trials(
                    rng, space, 0, rng.randint(1, 4), rng.randint(1, 4)
                )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sampler = CmaEsSampler(**kwargs)
                trans = _SearchSpaceTransform(
                    space, transform_step=not sampler._with_margin, transform_0_1=True
                )
                if kind == "no_compat":
                    with self.assertRaisesRegex(ValueError, "compatible"):
                        sampler._init_optimizer(trans, direction)
                    outcomes.append(None)
                    continue
                optimizer = sampler._init_optimizer(trans, direction)
            self.assertEqual(optimizer.dim, n_dim)
            outcomes.append(type(optimizer))

        self.assertEqual(len(outcomes), 20)
        self.assertIn(None, outcomes)
        self.assertTrue(
            all(o in (None, cmaes.CMA, cmaes.SepCMA, cmaes.CMAwM) for o in outcomes)
        )
