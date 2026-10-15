import random
import re
import sys
import unittest
from collections import deque

from werkzeug.debug import repr as debug_repr_mod
from werkzeug.debug.repr import DebugReprGenerator
from werkzeug.debug.repr import debug_repr
from werkzeug.debug.repr import dump
from werkzeug.debug.repr import helper


class _FakeStdout:
    def __init__(self):
        self.chunks = []

    def _write(self, s):
        self.chunks.append(s)

    def write(self, s):
        self.chunks.append(s)

    def flush(self):
        pass


class _Broken:
    def __init__(self, n):
        self.n = n

    def __repr__(self):
        if self.n % 3 == 0:
            raise ValueError(self.n)
        return f"<Broken {self.n}>"


class _Tagged(str):
    pass


class _Blob(bytes):
    pass


class _Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class TestDebugReprScenarios(unittest.TestCase):
    def test_seeded_flat_list(self):
        rng = random.Random(1307)
        data = []
        for _ in range(17):
            k = rng.randrange(4)
            if k == 0:
                data.append(rng.randint(-50, 50))
            elif k == 1:
                data.append(rng.random())
            elif k == 2:
                data.append("w" * rng.randint(1, 9))
            else:
                data.append(None)
        out = debug_repr(data)
        self.assertTrue(out.startswith("["))
        self.assertIn("extended", out)

    def test_dict_of_lists(self):
        d = {f"k{i}": list(range(i % 4)) for i in range(7)}
        out = debug_repr(d)
        self.assertIn('class="pair"', out)

    def test_recursive_structures(self):
        a = [1, 2]
        a.append(a)
        b = {"self": None, "n": 3}
        b["self"] = b
        c = (a, b, [a])
        out = debug_repr(c)
        self.assertIn("...", out)

    def test_long_and_subclassed_strings(self):
        items = [
            "x" * (60 + 5 * i) if i % 2 else _Tagged("t" * (i * 20))
            for i in range(6)
        ]
        items.append(_Blob(b"\x00" * 40))
        items.append(b"plain")
        out = debug_repr(items)
        self.assertIn("string", out)

    def test_regex_mix(self):
        pats = [re.compile(p) for p in (r"\d+", r"[a-z]{2,}", r"^x$")]
        pats.extend(p.pattern for p in pats[:2])
        out = debug_repr(tuple(pats))
        self.assertIn("regex", out)

    def test_sequence_flavours(self):
        seq = [
            set(range(3)),
            frozenset({5, 7}),
            deque([1.5, 2.5, 3.5]),
            (complex(1, 2), True),
            [[], ()],
        ]
        out = debug_repr(seq)
        self.assertIn("deque", out)

    def test_broken_reprs_and_helper(self):
        objs = [_Broken(n) for n in range(1, 8)]
        objs.insert(2, helper)
        out = debug_repr(objs)
        self.assertIn("brokenrepr", out)

    def test_dump_object_str_keyed_dict(self):
        gen = DebugReprGenerator()
        d = {name: (idx, name.upper()) for idx, name in enumerate("abcde")}
        out = gen.dump_object(d)
        self.assertIn("Contents of", out)

    def test_dump_object_mixed_key_dict(self):
        gen = DebugReprGenerator()
        d = {"first": 1, 2: "second", "third": [3]}
        out = gen.dump_object(d)
        self.assertIn("Details for", out)

    def test_dump_point_to_stdout(self):
        fake = _FakeStdout()
        old = sys.stdout
        sys.stdout = fake
        try:
            dump(_Point(4, [9, 8]))
        finally:
            sys.stdout = old
        self.assertEqual(len(fake.chunks), 1)

    def test_dump_locals_to_stdout(self):
        fake = _FakeStdout()

        def frame_owner():
            alpha = {"q": (1, 2)}
            beta = "beta" * 30
            gamma = _Broken(6)
            old = sys.stdout
            sys.stdout = fake
            try:
                dump()
            finally:
                sys.stdout = old
            return alpha, beta, gamma

        frame_owner()
        self.assertIn("Local variables", fake.chunks[0])

    def test_nested_generated_tree(self):
        def build(depth, width):
            if depth == 0:
                return depth * width
            if depth % 2:
                return [build(depth - 1, width) for _ in range(width)]
            return {f"n{j}": build(depth - 1, width) for j in range(width - 1)}

        out = debug_repr(build(3, 3))
        self.assertIn("{", out)

    def test_module_level_helpers(self):
        gen = debug_repr_mod.DebugReprGenerator()
        values = [0.25, -3, "", b"", (), {}, deque()]
        rendered = [gen.repr(v) for v in values]
        self.assertEqual(len(rendered), 7)
