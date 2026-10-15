from __future__ import annotations

import random
import unittest

from optuna.distributions import distribution_to_json
from optuna.distributions import FloatDistribution
from optuna.distributions import IntDistribution
from optuna.storages.journal._storage import JournalOperation
from optuna.storages.journal._storage import JournalStorageReplayResult
from optuna.trial import TrialState


FIXED_START = "2024-01-02T03:04:05.000000"
FIXED_COMPLETE = "2024-01-02T03:14:15.000000"


def _bootstrap_logs(rng: random.Random) -> list[dict]:
    """First batch: studies and an initial pool of trials."""
    logs: list[dict] = []
    names = [f"study-{i % 3}" for i in range(4)]  # last one duplicates an earlier name
    for name in names:
        logs.append(
            {
                "op_code": JournalOperation.CREATE_STUDY,
                "worker_id": "remote-a",
                "study_name": name,
                "directions": [rng.choice([1, 2])],
            }
        )
    for k in range(7):
        log = {
            "op_code": JournalOperation.CREATE_TRIAL,
            "worker_id": "remote-a",
            "study_id": (k * 2) % 4,  # study id 3 never exists
            "datetime_start": None,
        }
        if k % 3 == 2:
            log["state"] = TrialState.WAITING.value
        logs.append(log)
    return logs


def _mixed_logs(rng: random.Random, n: int) -> list[dict]:
    """Second batch: a seeded mixture of every operation kind."""
    float_dist = distribution_to_json(FloatDistribution(0.0, 1.0))
    int_dist = distribution_to_json(IntDistribution(0, 9))
    ops = [
        JournalOperation.SET_TRIAL_PARAM,
        JournalOperation.SET_TRIAL_STATE_VALUES,
        JournalOperation.SET_TRIAL_INTERMEDIATE_VALUE,
        JournalOperation.SET_TRIAL_USER_ATTR,
        JournalOperation.SET_TRIAL_SYSTEM_ATTR,
        JournalOperation.SET_STUDY_USER_ATTR,
        JournalOperation.SET_STUDY_SYSTEM_ATTR,
        JournalOperation.CREATE_TRIAL,
        JournalOperation.DELETE_STUDY,
        JournalOperation.DISCARD_TRIALS,
    ]
    weights = [5, 4, 3, 2, 2, 2, 2, 2, 1, 1]
    logs: list[dict] = []
    for step in range(n):
        op = rng.choices(ops, weights)[0]
        worker = f"remote-{'abc'[step % 3]}"
        log: dict = {"op_code": op, "worker_id": worker}
        if op in (
            JournalOperation.SET_STUDY_USER_ATTR,
            JournalOperation.SET_STUDY_SYSTEM_ATTR,
            JournalOperation.DELETE_STUDY,
            JournalOperation.CREATE_TRIAL,
        ):
            log["study_id"] = rng.randrange(4)
            if op == JournalOperation.SET_STUDY_USER_ATTR:
                log["user_attr"] = {f"u{step}": step}
            elif op == JournalOperation.SET_STUDY_SYSTEM_ATTR:
                log["system_attr"] = {f"s{step}": step * 2}
            elif op == JournalOperation.CREATE_TRIAL:
                log["datetime_start"] = None
        elif op == JournalOperation.DISCARD_TRIALS:
            log["trial_ids"] = [rng.randrange(8)]
        else:
            log["trial_id"] = rng.randrange(9)
            if op == JournalOperation.SET_TRIAL_PARAM:
                use_int = rng.random() < 0.3
                log["param_name"] = "x"
                log["param_value_internal"] = float(rng.randrange(10)) if use_int else rng.random()
                log["distribution"] = int_dist if use_int else float_dist
            elif op == JournalOperation.SET_TRIAL_STATE_VALUES:
                state = rng.choice(
                    [TrialState.RUNNING, TrialState.COMPLETE, TrialState.FAIL, TrialState.RUNNING]
                )
                log["state"] = state.value
                log["values"] = [rng.random()] if state == TrialState.COMPLETE else None
                log["datetime_start"] = FIXED_START if state == TrialState.RUNNING else None
                log["datetime_complete"] = FIXED_COMPLETE if state.is_finished() else None
            elif op == JournalOperation.SET_TRIAL_INTERMEDIATE_VALUE:
                log["step"] = step
                log["intermediate_value"] = rng.random()
            elif op == JournalOperation.SET_TRIAL_USER_ATTR:
                log["user_attr"] = {"tag": step}
            else:
                log["system_attr"] = {"sys": step}
        logs.append(log)
    return logs


class TestJournalReplayApplyLogs(unittest.TestCase):
    def test_replay_three_batches(self) -> None:
        rng = random.Random(6908)
        replay = JournalStorageReplayResult("replayer-")

        batch1 = _bootstrap_logs(rng)
        batch2 = _mixed_logs(rng, 30)
        batch3 = _mixed_logs(random.Random(len(batch2) * 7), 6)

        replay.apply_logs(batch1)
        replay.apply_logs(batch2)
        replay.apply_logs(batch3)

        self.assertEqual(replay.log_number_read, len(batch1) + len(batch2) + len(batch3))
        self.assertGreaterEqual(len(replay._trials), 5)
        self.assertLessEqual(len(replay.get_all_studies()), 3)
        for trial in replay._trials.values():
            self.assertIsInstance(trial.state, TrialState)


if __name__ == "__main__":
    unittest.main()
