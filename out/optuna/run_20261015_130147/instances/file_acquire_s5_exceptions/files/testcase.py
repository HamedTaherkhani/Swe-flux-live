from __future__ import annotations

import errno
import os
import random
from types import SimpleNamespace
import unittest
from unittest import mock

from optuna import exceptions
from optuna.storages.journal import _file
from optuna.storages.journal._file import JournalFileOpenLock


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        self.now += 0.4
        return self.now

    def sleep(self, secs: float) -> None:
        self.now += secs


class _FakeOS:
    """In-memory stand-in for the ``os`` functions used by the lock."""

    O_CREAT = os.O_CREAT
    O_EXCL = os.O_EXCL
    O_WRONLY = os.O_WRONLY

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.open_plan: list = []
        self.close_plan: list = []
        self.stat_failures: dict[int, int] = {}
        self.stat_calls = 0
        self.rename_calls = 0
        self.open_calls = 0

    def open(self, path: str, flags: int) -> int:
        self.open_calls += 1
        outcome = self.open_plan.pop(0) if self.open_plan else None
        if outcome is not None:
            raise OSError(outcome, os.strerror(outcome), path)
        return 7

    def close(self, fd: int) -> None:
        if self.close_plan:
            raise self.close_plan.pop(0)

    def stat(self, path: str) -> SimpleNamespace:
        self.stat_calls += 1
        code = self.stat_failures.get(self.stat_calls)
        if code is not None:
            raise OSError(code, os.strerror(code), path)
        return SimpleNamespace(st_mtime=float(self.stat_calls // 4))

    def rename(self, src: str, dst: str) -> None:
        self.rename_calls += 1
        if self.rng.random() < 0.5:
            raise OSError(errno.EBUSY, os.strerror(errno.EBUSY), src)

    def unlink(self, path: str) -> None:
        pass


class JournalFileOpenLockAcquireTest(unittest.TestCase):
    def test_acquire_under_contention(self) -> None:
        rng = random.Random(20261015)
        fake_os = _FakeOS(rng)
        clock = _FakeClock()
        fake_time = SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)

        busy = errno.EEXIST
        stat_codes = [errno.ENOENT, errno.ESTALE]
        terminal_codes = [errno.EINTR, errno.EAGAIN, errno.EACCES]

        results = []
        with mock.patch.object(_file, "os", fake_os), mock.patch.object(
            _file, "time", fake_time
        ):
            # Phase 1: no grace period, contention ends with a non-EEXIST error.
            lock = JournalFileOpenLock("/virtual/journal.log", grace_period=None)
            fake_os.open_plan = [busy] * rng.randint(8, 12) + [rng.choice(terminal_codes[:2])]
            try:
                results.append(lock.acquire())
            except Exception:
                results.append("raised")

            # Phase 2: grace period, sporadic stat failures, forced releases.
            lock = JournalFileOpenLock("/virtual/journal.log", grace_period=2)
            fake_os.open_plan = [busy] * rng.randint(22, 28)
            base = fake_os.stat_calls
            for k in rng.sample(range(1, 20), 5):
                fake_os.stat_failures[base + k] = rng.choice(stat_codes)
            try:
                results.append(lock.acquire())
            except Exception:
                results.append("raised")

            # Phase 3: lock file is created but closing it fails.
            lock = JournalFileOpenLock("/virtual/journal.log", grace_period=3)
            fake_os.open_plan = [busy] * rng.randint(5, 9)
            fake_os.close_plan = [exceptions.StorageInternalError("close failed")]
            try:
                results.append(lock.acquire())
            except Exception:
                results.append("raised")

            # Phase 4: long contention ending with an errno drawn at random.
            lock = JournalFileOpenLock("/virtual/journal.log", grace_period=5)
            fake_os.open_plan = [busy] * rng.randint(15, 20) + [rng.choice(terminal_codes)]
            try:
                results.append(lock.acquire())
            except Exception:
                results.append("raised")

        self.assertEqual(len(results), 4)
        self.assertIs(results[1], True)
        self.assertEqual(results.count("raised"), 3)
        self.assertGreater(fake_os.open_calls, 50)
        self.assertGreater(fake_os.stat_calls, 20)


if __name__ == "__main__":
    unittest.main()
