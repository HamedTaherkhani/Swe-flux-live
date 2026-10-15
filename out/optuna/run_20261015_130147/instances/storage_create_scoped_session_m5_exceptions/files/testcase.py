import random
import unittest
from unittest import mock

from sqlalchemy import text

import optuna
from optuna.distributions import CategoricalDistribution
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.storages import RDBStorage
from optuna.study import StudyDirection
from optuna.trial import TrialState


optuna.logging.set_verbosity(optuna.logging.ERROR)

URL = "sqlite:///:memory:"
MIN = StudyDirection.MINIMIZE
MAX = StudyDirection.MAXIMIZE


def _attempt(fn, *args, **kwargs):
    """Run ``fn`` and return (ok, result_or_exception)."""
    try:
        return True, fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        return False, e


class TestRDBStorageSessionScenarios(unittest.TestCase):
    def test_bulk_study_names_with_collisions(self):
        rng = random.Random(13)
        storage = RDBStorage(URL)
        pool = [f"s{i:02d}" for i in range(9)]
        names = [rng.choice(pool) for _ in range(27)]
        failures = 0
        for i, name in enumerate(names):
            directions = [MIN if (i + j) % 3 else MAX for j in range(1 + i % 3)]
            ok, _ = _attempt(storage.create_new_study, directions, name)
            failures += not ok
        self.assertEqual(failures, len(names) - len(set(names)))
        self.assertEqual(len(storage.get_all_studies()), len(set(names)))

    def test_lookup_generated_names(self):
        rng = random.Random(23)
        storage = RDBStorage(URL)
        created = sorted({f"exp-{rng.randint(0, 12)}" for _ in range(7)})
        for name in created:
            storage.create_new_study([MIN], name)
        probes = [f"exp-{rng.randint(0, 12)}" for _ in range(18)]
        found = 0
        for name in probes:
            ok, _ = _attempt(storage.get_study_id_from_name, name)
            found += ok
        self.assertEqual(found, sum(1 for p in probes if p in created))

    def test_clean_optimize_loop(self):
        storage = RDBStorage(URL)
        study = optuna.create_study(
            storage=storage, sampler=optuna.samplers.RandomSampler(seed=5)
        )
        study.optimize(
            lambda t: (t.suggest_float("x", -3, 3) - 1) ** 2 + t.suggest_int("k", 0, 4), n_trials=6
        )
        self.assertEqual(len(storage.get_all_trials(study._study_id)), 6)

    def test_param_writes_with_conflicts(self):
        rng = random.Random(37)
        storage = RDBStorage(URL)
        sid = storage.create_new_study([MIN], "params")
        tids = [storage.create_new_trial(sid) for _ in range(5)]
        dists = [
            FloatDistribution(0.0, 1.0),
            FloatDistribution(0.0, 2.0),
            IntDistribution(0, 10),
            CategoricalDistribution(["a", "b"]),
        ]
        outcomes = []
        for step in range(25):
            tid = rng.choice(tids)
            name = rng.choice(["alpha", "beta", "gamma"])
            dist = rng.choice(dists)
            value = float(rng.randint(0, 1))
            ok, _ = _attempt(storage.set_trial_param, tid, name, value, dist)
            outcomes.append(ok)
            if step == 10:
                storage.set_trial_state_values(tids[0], TrialState.COMPLETE, [0.0])
        self.assertGreater(len(outcomes), sum(outcomes))

    def test_updates_after_completion(self):
        rng = random.Random(41)
        storage = RDBStorage(URL)
        sid = storage.create_new_study([MIN, MAX], "updates")
        tids = [storage.create_new_trial(sid) for _ in range(8)]
        for tid in tids[::3]:
            storage.set_trial_state_values(tid, TrialState.COMPLETE, [1.0, 2.0])
        rejected = 0
        for step in range(16):
            tid = rng.choice(tids)
            if step % 2:
                ok, _ = _attempt(storage.set_trial_intermediate_value, tid, step, step * 0.5)
            else:
                ok, _ = _attempt(storage.set_trial_user_attr, tid, f"k{step}", step)
            rejected += not ok
        for tid in tids:
            _attempt(storage.set_trial_state_values, tid, TrialState.PRUNED)
        self.assertGreaterEqual(rejected, 1)
        states = {t.state for t in storage.get_all_trials(sid)}
        self.assertIn(TrialState.PRUNED, states)

    def test_dropped_trials_table_retries(self):
        random.seed(3)
        storage = RDBStorage(URL)
        sid = storage.create_new_study([MIN], "dropped")
        storage.create_new_trial(sid)
        with storage.engine.begin() as conn:
            conn.execute(text("DROP TABLE trials"))
        with mock.patch("time.sleep"):
            with self.assertRaises(Exception):
                storage.create_new_trial(sid)
        study = optuna.load_study(study_name="dropped", storage=storage)
        with self.assertRaises(Exception):
            study.ask()

    def test_unserializable_attributes(self):
        rng = random.Random(53)
        storage = RDBStorage(URL)
        sid = storage.create_new_study([MIN], "attrs")
        tid = storage.create_new_trial(sid)
        candidates = [1, "txt", [1, 2], {"a": 1}, {1, 2}, object(), b"raw", None, 2.5]
        bad = 0
        for i in range(14):
            value = rng.choice(candidates)
            if i % 2:
                ok, _ = _attempt(storage.set_study_user_attr, sid, f"u{i}", value)
            else:
                ok, _ = _attempt(storage.set_trial_system_attr, tid, f"s{i}", value)
            bad += not ok
        self.assertGreaterEqual(bad, 1)

    def test_lookups_by_random_ids(self):
        rng = random.Random(67)
        storage = RDBStorage(URL)
        sids = [storage.create_new_study([MIN], f"ids{i}") for i in range(3)]
        for sid in sids:
            for _ in range(sid):
                storage.create_new_trial(sid)
        hits = 0
        for i in range(15):
            ident = rng.randint(1, 9)
            getter = [
                storage.get_study_directions,
                storage.get_all_trials,
                storage.get_trial,
            ][i % 3]
            ok, _ = _attempt(getter, ident)
            hits += ok
        self.assertLess(hits, 15)

    def test_trial_numbers_lookup(self):
        storage = RDBStorage(URL)
        sid = storage.create_new_study([MAX], "numbers")
        for _ in range(4):
            storage.create_new_trial(sid)
        results = [
            _attempt(storage.get_trial_id_from_study_id_trial_number, sid, n)[0]
            for n in range(0, 12, 2)
        ]
        self.assertIn(True, results)
        self.assertIn(False, results)

    def test_storage_without_tables(self):
        for i in range(3):
            with self.assertRaises(Exception):
                RDBStorage(URL, skip_table_creation=True, skip_compatibility_check=bool(i % 2))

    def test_heartbeat_and_listing_safe(self):
        storage = RDBStorage(URL, heartbeat_interval=60, grace_period=120)
        sid = storage.create_new_study([MIN], "hb")
        tids = [storage.create_new_trial(sid) for _ in range(4)]
        for tid in tids:
            storage.record_heartbeat(tid)
        storage.record_heartbeat(tids[1])
        self.assertEqual(storage._get_stale_trial_ids(sid), [])
        self.assertEqual(len(storage.get_all_studies()), 1)

    def test_reload_and_delete_studies(self):
        storage = RDBStorage(URL)
        for i in range(4):
            optuna.create_study(storage=storage, study_name=f"r{i % 2}", load_if_exists=True)
        sid = storage.get_study_id_from_name("r1")
        storage.delete_study(sid)
        outcomes = [_attempt(storage.delete_study, sid)[0] for _ in range(2)]
        outcomes.append(_attempt(storage.get_study_name_from_id, sid)[0])
        self.assertEqual(outcomes.count(True), 0)


if __name__ == "__main__":
    unittest.main()
