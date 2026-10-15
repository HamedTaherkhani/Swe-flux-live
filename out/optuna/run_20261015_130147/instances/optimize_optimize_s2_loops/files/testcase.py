"""Deterministic exercise of the n_jobs > 1 submission loop of `_optimize`."""

from __future__ import annotations

from concurrent.futures import Future
import random
import unittest
from unittest import mock

import optuna
from optuna.study import _optimize as optimize_module
from optuna.trial import TrialState


class _InlineExecutor:
    """Drop-in replacement for ThreadPoolExecutor that runs each task immediately.

    Every submitted task runs synchronously in the calling thread, and the returned
    Future is already finished, which makes the submission loop fully deterministic.
    """

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers
        self.submitted = 0

    def __enter__(self) -> "_InlineExecutor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def submit(self, fn, *args, **kwargs) -> Future:
        self.submitted += 1
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as e:  # pragma: no cover - not expected here
            fut.set_exception(e)
        return fut


def _build_plan(seed: int, size: int) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    plan = []
    for k in range(size):
        a = rng.uniform(-4.0, 4.0)
        b = rng.uniform(-4.0, 4.0) + (k % 5) * 0.25
        plan.append((round(a, 4), round(b, 4)))
    return plan


class TestOptimizeInlineParallel(unittest.TestCase):
    def test_parallel_submission_loop_until_stop(self) -> None:
        plan = _build_plan(seed=20240611, size=120)

        def objective(trial: optuna.trial.Trial) -> float:
            a, b = plan[trial.number]
            prod = a * b
            if -1.5 < prod < 0.0:
                raise ValueError(f"bad region {prod:.3f}")
            if a + b > 5.0:
                raise optuna.TrialPruned()
            return (a - 1.0) ** 2 + (b + 0.5) ** 2

        state = {"improvements": 0, "best": float("inf")}

        def callback(study: optuna.Study, frozen: optuna.trial.FrozenTrial) -> None:
            if frozen.state == TrialState.COMPLETE and frozen.value < state["best"]:
                state["best"] = frozen.value
                if frozen.number >= 6:
                    state["improvements"] += 1
            n_fail = sum(1 for t in study.trials if t.state == TrialState.FAIL)
            if state["improvements"] >= 3 and n_fail >= 4:
                study.stop()

        study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
        with mock.patch.object(optimize_module, "ThreadPoolExecutor", _InlineExecutor):
            optimize_module._optimize(
                study,
                objective,
                n_trials=len(plan),
                n_jobs=3,
                catch=(ValueError,),
                callbacks=[callback],
            )

        states = [t.state for t in study.trials]
        self.assertGreater(len(states), 10)
        self.assertLess(len(states), len(plan))
        self.assertIn(TrialState.FAIL, states)
        self.assertIn(TrialState.COMPLETE, states)
        self.assertFalse(study._thread_local.in_optimize_loop)


if __name__ == "__main__":
    unittest.main()
