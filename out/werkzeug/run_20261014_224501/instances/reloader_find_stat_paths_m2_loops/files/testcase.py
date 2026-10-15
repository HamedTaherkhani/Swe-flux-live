import os
import random
import sys
import tempfile
import unittest
from unittest import mock

from werkzeug._reloader import StatReloaderLoop

SUFFIXES = [".py", ".pyc", ".txt", ".pyi", ".cfg", ".pyx", ".py.bak"]
SPECIAL_DIRS = ["__pycache__", ".git", ".tox", "pkg", "data", "lib"]


def grow(rng, root, depth, fanout, files_per_dir, special_rate=0.2):
    """Create a random directory tree below ``root``."""
    os.makedirs(root, exist_ok=True)
    for i in range(rng.randint(0, files_per_dir)):
        suffix = rng.choice(SUFFIXES)
        with open(os.path.join(root, f"f{i}{suffix}"), "w") as fh:
            fh.write("x = %d\n" % i)
    if depth <= 0:
        return
    for j in range(rng.randint(1, fanout)):
        if rng.random() < special_rate:
            name = rng.choice(SPECIAL_DIRS)
        else:
            name = f"d{j}"
        grow(rng, os.path.join(root, name), depth - 1, fanout, files_per_dir, special_rate)


def touch(path, text="pass\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class FindStatPathsLoopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self._tmp.name)
        self.reloads = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_loop(self, search_path, extra_files=(), exclude=(), steps=1, between=None):
        with mock.patch.object(sys, "path", list(search_path)):
            with mock.patch.object(
                StatReloaderLoop, "trigger_reload", lambda s, n: self.reloads.append(n)
            ):
                loop = StatReloaderLoop(extra_files=extra_files, exclude_patterns=exclude)
                with loop:
                    for _ in range(steps - 1):
                        if between is not None:
                            between()
                        loop.run_step()
        return loop

    def watched(self, loop):
        return sorted(p for p in loop.mtimes if p.startswith(self.base))

    def test_small_random_tree(self):
        root = os.path.join(self.base, "proj")
        grow(random.Random(11), root, depth=3, fanout=3, files_per_dir=5)
        loop = self.run_loop([root])
        for p in self.watched(loop):
            self.assertTrue(p.endswith((".py", ".pyc")))

    def test_deep_tree_with_pruning(self):
        root = os.path.join(self.base, "deep")
        grow(random.Random(23), root, depth=5, fanout=3, files_per_dir=4, special_rate=0.1)
        loop = self.run_loop([root])
        self.assertIsInstance(loop.mtimes, dict)

    def test_no_python_chain(self):
        root = os.path.join(self.base, "chain")
        cur = root
        for level in range(6):
            cur = os.path.join(cur, f"lvl{level}")
            for k in range(level % 3 + 1):
                touch(os.path.join(cur, f"notes{k}.txt"))
        touch(os.path.join(root, "top.py"))
        touch(os.path.join(cur, "hidden.py"))
        loop = self.run_loop([root])
        self.assertNotIn(os.path.join(cur, "hidden.py"), loop.mtimes)

    def test_ignored_directories(self):
        root = os.path.join(self.base, "ign")
        for name in ["__pycache__", ".git", ".mypy_cache", ".nox", "src"]:
            for k in range(4):
                touch(os.path.join(root, name, f"m{k}.py"))
        touch(os.path.join(root, "src", ".hg", "inner.py"))
        loop = self.run_loop([root])
        self.assertEqual(len(self.watched(loop)), 4)

    def test_extra_files_and_dirs(self):
        root = os.path.join(self.base, "main")
        grow(random.Random(5), root, depth=2, fanout=2, files_per_dir=5)
        extra_dir = os.path.join(self.base, "extra")
        grow(random.Random(6), extra_dir, depth=1, fanout=3, files_per_dir=3)
        extra_file = os.path.join(self.base, "settings.cfg")
        touch(extra_file)
        loop = self.run_loop([root], extra_files=[extra_dir, extra_file])
        self.assertIn(extra_file, loop.mtimes)

    def test_missing_and_file_entries(self):
        archive = os.path.join(self.base, "bundle.zip")
        touch(archive, "PK")
        missing = os.path.join(self.base, "does", "not", "exist")
        root = os.path.join(self.base, "real")
        grow(random.Random(7), root, depth=1, fanout=4, files_per_dir=2)
        loop = self.run_loop([missing, archive, root, missing])
        self.assertIn(archive, loop.mtimes)

    def test_two_steps_with_new_files(self):
        root = os.path.join(self.base, "grow")
        rng = random.Random(31)
        grow(rng, root, depth=2, fanout=2, files_per_dir=3)

        def add_more():
            grow(rng, os.path.join(root, "late"), depth=1, fanout=3, files_per_dir=4)

        loop = self.run_loop([root], steps=2, between=add_more)
        self.assertTrue(len(loop.mtimes) > 0)

    def test_nested_search_path(self):
        root = os.path.join(self.base, "outer")
        grow(random.Random(41), root, depth=3, fanout=2, files_per_dir=3, special_rate=0.0)
        inner = os.path.join(root, "d0")
        touch(os.path.join(inner, "anchor.py"))
        loop = self.run_loop([root, inner])
        self.assertIn(os.path.join(inner, "anchor.py"), loop.mtimes)

    def test_wide_flat_tree(self):
        root = os.path.join(self.base, "wide")
        rng = random.Random(53)
        for i in range(9):
            sub = os.path.join(root, f"w{i}")
            for k in range(rng.randint(1, 5)):
                touch(os.path.join(sub, f"x{k}{rng.choice(SUFFIXES)}"))
        loop = self.run_loop([root])
        self.assertTrue(all(p.startswith(root) for p in self.watched(loop)))

    def test_exclude_patterns(self):
        root = os.path.join(self.base, "excl")
        grow(random.Random(61), root, depth=3, fanout=3, files_per_dir=5)
        loop = self.run_loop([root], exclude=["*/d0/*", "*.pyc"])
        for p in self.watched(loop):
            self.assertFalse(p.endswith(".pyc"))

    def test_search_root_is_cache_dir(self):
        root = os.path.join(self.base, "__pycache__")
        grow(random.Random(71), root, depth=2, fanout=2, files_per_dir=4)
        other = os.path.join(self.base, "sibling")
        for k in range(3):
            touch(os.path.join(other, f"s{k}.pyc"))
        loop = self.run_loop([root, other])
        self.assertEqual(len(self.watched(loop)), 3)

    def test_modified_file_triggers_reload(self):
        root = os.path.join(self.base, "mod")
        grow(random.Random(83), root, depth=2, fanout=2, files_per_dir=4)
        target = os.path.join(root, "app.py")
        touch(target)

        def bump():
            st = os.stat(target)
            os.utime(target, (st.st_atime + 100, st.st_mtime + 100))

        self.run_loop([root], steps=3, between=bump)
        self.assertTrue(self.reloads)
        self.assertTrue(all(r == target for r in self.reloads))
