import os
import random
import shutil
import tempfile
import unittest
from unittest import mock
import warnings

from optuna.storages.journal import _file
from optuna.storages.journal._file import JournalFileSymlinkLock


class _Clock:
    """Deterministic replacement for the ``time`` module used inside ``_file``.

    ``monotonic()`` advances the virtual clock by ``step`` on every call and ``sleep(s)``
    advances it by ``s``. Optional hooks run on the n-th (1-based) monotonic / sleep call and
    simulate what a concurrent process does to the lock file meanwhile.
    """

    def __init__(self, step=0.001, on_mono=None, on_sleep=None):
        self.now = 1000.0
        self.step = step
        self.mono_calls = 0
        self.sleep_calls = 0
        self.slept = []
        self.on_mono = on_mono or {}
        self.on_sleep = on_sleep or {}

    def monotonic(self):
        self.mono_calls += 1
        self.now += self.step
        hook = self.on_mono.get(self.mono_calls)
        if hook is not None:
            hook()
        return self.now

    def sleep(self, secs):
        self.sleep_calls += 1
        self.slept.append(secs)
        self.now += secs
        hook = self.on_sleep.get(self.sleep_calls)
        if hook is not None:
            hook()


class TestJournalFileSymlinkLockAcquireMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="symlock_")
        self.rng = random.Random(20240611)
        warnings.simplefilter("ignore")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def _journal(self, name):
        path = os.path.join(self.tmp, name)
        open(path, "ab").close()
        return path

    def _hold(self, lock):
        # Another "process" holds the lock: the lock symlink already exists.
        os.symlink(lock._lock_target_file, lock._lock_file)

    def _drop(self, lock):
        return lambda: os.path.lexists(lock._lock_file) and os.unlink(lock._lock_file)

    def _acquire(self, lock, clock):
        with mock.patch.object(_file, "time", clock):
            return lock.acquire()

    # ------------------------------------------------------------------ tests
    def test_uncontended_cycles(self):
        names = ["j%02d.log" % (self.rng.randrange(97) * 3 % 41) for _ in range(17)]
        acquired = 0
        for name in names:
            lock = JournalFileSymlinkLock(self._journal(name), grace_period=None)
            if self._acquire(lock, _Clock()):
                acquired += 1
            lock.release()
        self.assertEqual(acquired, len(names))

    def test_holder_releases_after_waits(self):
        lock = JournalFileSymlinkLock(self._journal("held.log"), grace_period=None)
        self._hold(lock)
        waits = sum(self.rng.randint(1, 4) for _ in range(4))
        clock = _Clock(on_sleep={waits: self._drop(lock)})
        self.assertTrue(self._acquire(lock, clock))
        self.assertEqual(clock.sleep_calls, waits)
        self.assertTrue(os.path.islink(lock._lock_file))
        lock.release()

    def test_rounds_with_long_grace(self):
        lock = JournalFileSymlinkLock(self._journal("rounds.log"), grace_period=30)
        total_sleeps = 0
        for _ in range(5):
            self._hold(lock)
            waits = self.rng.randint(0, 6)
            if waits == 0:
                lock.release()
            clock = _Clock(step=0.25, on_sleep={waits: self._drop(lock)})
            self.assertTrue(self._acquire(lock, clock))
            total_sleeps += clock.sleep_calls
            lock.release()
        self.assertGreater(total_sleeps, 0)

    def test_stale_lock_forcibly_released(self):
        lock = JournalFileSymlinkLock(self._journal("stale.log"), grace_period=3)
        self._hold(lock)
        clock = _Clock(step=0.4)
        self.assertTrue(self._acquire(lock, clock))
        self.assertGreater(clock.sleep_calls, 1)
        lock.release()

    def test_missing_lock_directories(self):
        failures = 0
        for i in range(6):
            if self.rng.random() < 0.5:
                path = os.path.join(self.tmp, "nowhere%d" % i, "j.log")
            else:
                path = self._journal("ok%d.log" % i)
            lock = JournalFileSymlinkLock(path, grace_period=None)
            try:
                self._acquire(lock, _Clock())
            except Exception:
                failures += 1
            else:
                lock.release()
        self.assertGreater(failures, 0)
        self.assertLess(failures, 6)

    def test_parent_is_regular_file(self):
        blocker = self._journal("blocker")
        lock = JournalFileSymlinkLock(os.path.join(blocker, "j.log"), grace_period=5)
        with self.assertRaises(Exception):
            self._acquire(lock, _Clock())
        self.assertFalse(os.path.lexists(lock._lock_file))

    def test_dangling_lock_until_journal_appears(self):
        path = os.path.join(self.tmp, "late.log")
        lock = JournalFileSymlinkLock(path, grace_period=50)
        self._hold(lock)
        appear_at = self.rng.randint(3, 9)
        clock = _Clock(
            step=0.1,
            on_mono={appear_at: lambda: open(path, "ab").close()},
            on_sleep={3: self._drop(lock)},
        )
        self.assertTrue(self._acquire(lock, clock))
        lock.release()

    def test_unrenamable_stale_lock(self):
        path = self._journal("L" * 220 + ".log")
        lock = JournalFileSymlinkLock(path, grace_period=3)
        self._hold(lock)
        give_up_at = 14 + self.rng.randint(0, 5)
        clock = _Clock(step=2.0, on_mono={give_up_at: self._drop(lock)})
        self.assertTrue(self._acquire(lock, clock))
        self.assertTrue(os.path.islink(lock._lock_file))
        os.unlink(lock._lock_file)

    def test_null_byte_target_unheld(self):
        lock = JournalFileSymlinkLock(self._journal("nb.log"), grace_period=None)
        lock._lock_target_file = lock._lock_target_file + "\x00"
        with self.assertRaises(Exception):
            self._acquire(lock, _Clock())
        self.assertFalse(os.path.lexists(lock._lock_file))

    def test_bad_target_type_while_held(self):
        lock = JournalFileSymlinkLock(self._journal("tt.log"), grace_period=None)
        self._hold(lock)
        lock._lock_target_file = None
        with self.assertRaises(Exception):
            self._acquire(lock, _Clock())
        # The failed acquire removed the foreign lock on its way out.
        self.assertFalse(os.path.lexists(lock._lock_file))

    def test_seeded_mixed_workload(self):
        outcomes = []
        for i in range(20):
            kind = self.rng.choice(["free", "held", "held", "gone"])
            if kind == "gone":
                path = os.path.join(self.tmp, "gone%d" % i, "j.log")
            else:
                path = self._journal("mix%d.log" % i)
            lock = JournalFileSymlinkLock(path, grace_period=None)
            clock = _Clock()
            if kind == "held":
                self._hold(lock)
                clock.on_sleep[1 + (i * 7) % 5] = self._drop(lock)
            try:
                self._acquire(lock, clock)
            except Exception:
                outcomes.append("fail")
            else:
                outcomes.append("ok")
                lock.release()
        self.assertEqual(len(outcomes), 20)
        self.assertIn("fail", outcomes)

    def test_long_wait_with_warnings(self):
        lock = JournalFileSymlinkLock(self._journal("slow.log"), grace_period=None)
        self._hold(lock)
        waits = 9 + self.rng.randint(0, 6)
        clock = _Clock(step=3.5, on_sleep={waits: self._drop(lock)})
        self.assertTrue(self._acquire(lock, clock))
        self.assertEqual(max(clock.slept), 1)
        lock.release()

    def test_dangling_then_stale_steal(self):
        path = os.path.join(self.tmp, "ghost.log")
        lock = JournalFileSymlinkLock(path, grace_period=4)
        self._hold(lock)
        clock = _Clock(step=0.75, on_mono={5: lambda: open(path, "ab").close()})
        self.assertTrue(self._acquire(lock, clock))
        lock.release()
        self.assertFalse(os.path.lexists(lock._lock_file))


if __name__ == "__main__":
    unittest.main()
