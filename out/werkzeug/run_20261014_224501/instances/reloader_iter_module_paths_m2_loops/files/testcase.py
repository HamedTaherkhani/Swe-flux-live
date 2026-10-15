import os
import random
import types
import unittest
from unittest import mock

from werkzeug import _reloader
from werkzeug._reloader import StatReloaderLoop

# All relative paths below are resolved against the repository root, which is
# the working directory pytest is launched from.
PKG_DIR = os.path.join("src", "werkzeug")
SEGMENTS = ["alpha", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta"]
SUBDIRS = ["sansio", "debug", "routing", "middleware", "datastructures"]


def repo_files():
    return sorted(n for n in os.listdir(PKG_DIR) if n.endswith(".py"))


class FakeModule:
    """Minimal stand-in for a module object."""

    def __init__(self, file=..., label=""):
        self.label = label
        if file is not ...:
            self.__file__ = file


def make_path(rng, kind):
    """Return a fake ``__file__`` value of the requested kind."""
    files = repo_files()
    if kind == "real":
        return os.path.join(PKG_DIR, rng.choice(files))
    if kind == "zip":
        tail = [rng.choice(SEGMENTS) for _ in range(rng.randint(1, 4))]
        return os.path.join(PKG_DIR, rng.choice(files), *tail) + ".py"
    if kind == "ghost":
        parts = [rng.choice(SEGMENTS) for _ in range(rng.randint(1, 5))]
        return os.path.join("ghost", *parts)
    if kind == "abs_ghost":
        parts = [rng.choice(SEGMENTS) for _ in range(rng.randint(1, 3))]
        return "/" + "/".join(["nowhere", *parts])
    if kind == "dir":
        path = os.path.join(PKG_DIR, rng.choice(SUBDIRS))
        return path + ("/" * rng.randint(0, 2))
    if kind == "system":
        suffix = rng.choice(["", "x", "/lib"])
        return f"/usr/local{suffix}/{rng.choice(SEGMENTS)}/mod.py"
    if kind == "none":
        return None
    if kind == "missing":
        return ...
    if kind == "empty":
        return ""
    if kind == "root":
        return "/" * rng.randint(1, 3)
    raise AssertionError(kind)


def make_modules(seed, count, kinds, weights=None, prefix="m"):
    rng = random.Random(seed)
    modules = {}
    for i in range(count):
        kind = rng.choices(kinds, weights=weights)[0]
        modules[f"{prefix}{i}"] = FakeModule(make_path(rng, kind), label=kind)
    return modules


class IterModulePathsLoopTest(unittest.TestCase):
    def setUp(self):
        self.reloads = []

    def fake_sys(self, modules, path=()):
        return types.SimpleNamespace(modules=modules, path=list(path))

    def run_stat(self, modules, path=(), extra=(), exclude=(), steps=1, between=None):
        fake = self.fake_sys(modules, path)
        with mock.patch.object(_reloader, "sys", fake), mock.patch.object(
            StatReloaderLoop, "trigger_reload", lambda s, n: self.reloads.append(n)
        ):
            loop = StatReloaderLoop(extra_files=extra, exclude_patterns=exclude)
            with loop:
                for step in range(steps - 1):
                    if between is not None:
                        between(fake, step)
                    loop.run_step()
        return loop

    def test_mostly_real_files(self):
        modules = make_modules(11, 18, ["real", "none", "missing", "zip"], [6, 1, 1, 1])
        loop = self.run_stat(modules)
        self.assertTrue(all(p.endswith(".py") for p in loop.mtimes))
        self.assertEqual(self.reloads, [])

    def test_zip_style_paths(self):
        modules = make_modules(23, 20, ["zip", "real"], [3, 1])
        loop = self.run_stat(modules)
        self.assertTrue(loop.mtimes)
        self.assertTrue(all(os.path.isfile(p) for p in loop.mtimes))

    def test_ghost_relative_paths(self):
        modules = make_modules(37, 16, ["ghost", "zip"], [2, 1])
        loop = self.run_stat(modules)
        self.assertFalse(any(p.startswith("ghost") for p in loop.mtimes))

    def test_absolute_ghosts_and_roots(self):
        modules = make_modules(41, 14, ["abs_ghost", "root", "real"], [3, 2, 1])
        loop = self.run_stat(modules)
        self.assertFalse(any(p.startswith("/nowhere") for p in loop.mtimes))

    def test_system_prefix_mix(self):
        modules = make_modules(53, 24, ["system", "zip", "ghost", "none"], [3, 2, 2, 1])
        loop = self.run_stat(modules)
        self.assertFalse(any(p.startswith("/usr/local") for p in loop.mtimes))

    def test_directory_paths(self):
        modules = make_modules(67, 15, ["dir", "empty", "real"], [4, 1, 1])
        loop = self.run_stat(modules)
        self.assertTrue(all(os.path.isfile(p) for p in loop.mtimes))

    def test_growing_modules_between_steps(self):
        modules = make_modules(79, 6, ["zip", "ghost"])

        def grow(fake, step):
            extra = make_modules(100 + step, 3 + 2 * step, ["zip", "ghost", "real"], prefix=f"g{step}_")
            fake.modules.update(extra)

        self.run_stat(modules, steps=4, between=grow)
        self.assertGreater(len(modules), 6)

    def test_shrinking_modules_between_steps(self):
        modules = make_modules(83, 22, ["zip", "abs_ghost", "dir", "real"])

        def shrink(fake, step):
            for key in sorted(fake.modules)[: 4 + step]:
                del fake.modules[key]

        self.run_stat(modules, steps=3, between=shrink)
        self.assertLess(len(modules), 22)

    def test_exclude_patterns_do_not_change_scan(self):
        modules = make_modules(97, 17, ["zip", "real", "ghost"], [2, 2, 1])
        loop = self.run_stat(modules, exclude={"*/_*.py", "*/http.py"})
        self.assertFalse(any(os.path.basename(p).startswith("_") for p in loop.mtimes))

    def test_with_extra_files_and_search_path(self):
        modules = make_modules(109, 12, ["zip", "dir", "root"], [2, 1, 1])
        extra = [os.path.join(PKG_DIR, "utils.py")]
        loop = self.run_stat(modules, path=[os.path.join(PKG_DIR, "debug")], extra=extra)
        self.assertIn(os.path.abspath(extra[0]), loop.mtimes)

    def test_watchdog_dir_discovery(self):
        modules = make_modules(127, 19, ["zip", "real", "system", "ghost", "dir"])
        fake = self.fake_sys(modules)
        with mock.patch.object(_reloader, "sys", fake):
            roots = _reloader._find_watchdog_paths(set(), set())
        self.assertTrue(roots)

    def test_mixed_everything(self):
        kinds = ["real", "zip", "ghost", "abs_ghost", "dir", "system", "none", "missing", "empty", "root"]
        modules = make_modules(131, 30, kinds)

        def swap(fake, step):
            rng = random.Random(step)
            for key in sorted(fake.modules)[::3]:
                fake.modules[key] = FakeModule(make_path(rng, "zip"), label="zip")

        self.run_stat(modules, steps=2, between=swap)
        self.assertEqual(self.reloads, [])
