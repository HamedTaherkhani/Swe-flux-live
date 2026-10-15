import random
import unittest
from datetime import datetime
from datetime import timedelta

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.storages import RDBStorage
from optuna.storages._rdb.storage import _create_scoped_session
from optuna.study import StudyDirection
from optuna.trial import FrozenTrial
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)

PARAM_SPACE = {
    "lr": FloatDistribution(1e-4, 1.0, log=True),
    "depth": IntDistribution(1, 12),
    "act": CategoricalDistribution(["relu", "tanh", "gelu"]),
    "drop": FloatDistribution(0.0, 0.5),
    "width": IntDistribution(8, 256, step=8),
}
STATES = [TrialState.RUNNING, TrialState.COMPLETE, TrialState.PRUNED, TrialState.FAIL]
BASE_TIME = datetime(2024, 1, 1, 12, 0, 0)


def _sample_param(rng, dist):
    if isinstance(dist, FloatDistribution):
        return dist.low + (dist.high - dist.low) * rng.random()
    if isinstance(dist, IntDistribution):
        return rng.randrange(dist.low, dist.high + 1, dist.step)
    return rng.choice(dist.choices)


def _build_template(rng, idx):
    if rng.random() < 0.15:
        return None
    state = STATES[(idx * 3 + rng.randint(0, 3)) % len(STATES)]
    n_obj = rng.choice([0, 1, 1, 2, 3])
    values = [round(rng.uniform(-5, 5), 3) for _ in range(n_obj)] or None
    if state == TrialState.COMPLETE and values is None:
        values = [round(rng.uniform(0, 1), 3)]
    names = [n for n in PARAM_SPACE if rng.random() < 0.6]
    rng.shuffle(names)
    params = {n: _sample_param(rng, PARAM_SPACE[n]) for n in names}
    user_attrs = {f"u{k}": rng.randint(0, 99) for k in range(5) if (k + idx) % 3 != 0}
    system_attrs = {f"sys_{k}": [k, idx] for k in range(rng.randint(0, 3))}
    steps = sorted({rng.randint(0, 9) for _ in range(rng.randint(0, 6))}, reverse=idx % 2 == 1)
    inter = {s: s * 0.5 - idx for s in steps}
    start = BASE_TIME + timedelta(minutes=idx)
    return FrozenTrial(
        number=-1,
        state=state,
        value=None,
        values=values,
        datetime_start=start,
        datetime_complete=start + timedelta(seconds=30) if state.is_finished() else None,
        params=params,
        distributions={n: PARAM_SPACE[n] for n in names},
        user_attrs=user_attrs,
        system_attrs=system_attrs,
        intermediate_values=inter,
        trial_id=-1,
    )


class TestPreparedNewTrial(unittest.TestCase):
    def test_prepare_many_templates(self):
        rng = random.Random(4242)
        storage = RDBStorage("sqlite:///:memory:")
        study_id = storage.create_new_study([StudyDirection.MINIMIZE, StudyDirection.MAXIMIZE])
        templates = [_build_template(rng, i) for i in range(9)]
        numbers = []
        for template in templates:
            with _create_scoped_session(storage.scoped_session, True) as session:
                trial = storage._get_prepared_new_trial(study_id, template, session)
                numbers.append(trial.number)
        self.assertEqual(numbers, list(range(len(templates))))
        stored = storage.get_all_trials(study_id, deepcopy=False)
        self.assertEqual(len(stored), len(templates))
        for t, tmpl in zip(stored, templates):
            if tmpl is not None:
                self.assertEqual(t.state, tmpl.state)
                self.assertEqual(set(t.params), set(tmpl.params))
