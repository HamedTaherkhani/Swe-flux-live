import random
import unittest
import warnings

import optuna
from optuna.study._tell import _tell_with_warning
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)


def _make_payload(rng, n_obj):
    """Build a (value_or_values, state) pair from the RNG."""
    kind = rng.randrange(7)
    if kind == 0:
        return [rng.uniform(-5.0, 5.0) for _ in range(n_obj)], TrialState.COMPLETE
    if kind == 1:
        size = rng.choice([n_obj - 1, n_obj, n_obj + 1])
        vals = [rng.uniform(-5.0, 5.0) for _ in range(size)]
        if rng.random() < 0.4 and vals:
            vals[rng.randrange(len(vals))] = float("nan")
        return vals, None
    if kind == 2:
        return None, TrialState.PRUNED
    if kind == 3:
        return None, rng.choice([None, TrialState.FAIL])
    if kind == 4:
        vals = [rng.randint(-3, 3) for _ in range(n_obj)]
        if rng.random() < 0.5:
            vals[0] = "v%d" % rng.randint(0, 9)
        return tuple(vals), rng.choice([None, TrialState.COMPLETE])
    if kind == 5:
        return rng.uniform(0.0, 1.0), rng.choice([None, TrialState.COMPLETE])
    return [float("nan")] * n_obj, rng.choice([None, TrialState.COMPLETE])


class TestTellWithWarningFlow(unittest.TestCase):
    def test_many_tells(self):
        rng = random.Random(20241015)
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.RandomSampler(seed=7),
        )
        n_obj = len(study.directions)
        outcomes = []
        finished = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(24):
                trial = study.ask()
                for step in range(rng.randrange(3)):
                    trial.report(rng.choice([rng.uniform(0.0, 2.0), float("nan")]), step)
                payload, state = _make_payload(rng, n_obj)
                target = trial.number if i % 3 == 0 else trial
                try:
                    res = _tell_with_warning(
                        study,
                        target,
                        payload,
                        state,
                        suppress_warning=bool(rng.getrandbits(1)),
                    )
                    outcomes.append(res[0])
                    finished.append(trial.number)
                except ValueError:
                    outcomes.append("error")
                    _tell_with_warning(study, trial, state=TrialState.FAIL)
                    finished.append(trial.number)
                if i % 5 == 4:
                    again = finished[rng.randrange(len(finished))]
                    skip = rng.random() < 0.6
                    try:
                        res = _tell_with_warning(
                            study, again, 0.0, skip_if_finished=skip
                        )
                        self.assertTrue(res[0].is_finished())
                    except ValueError as e:
                        self.assertIn("Cannot tell", str(e))

        self.assertEqual(len(outcomes), 24)
        self.assertTrue(all(t.state.is_finished() for t in study.trials))
        self.assertGreater(outcomes.count("error"), 0)
        self.assertGreater(sum(1 for o in outcomes if o == TrialState.COMPLETE), 0)
