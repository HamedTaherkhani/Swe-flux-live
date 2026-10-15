import random
import unittest

from werkzeug.debug.tbtools import _process_traceback

_HIDE_CHOICES = [False, False, False, "before", "reset", "after", "after_and_this",
                 "reset_and_this", "before_and_this", True]


def _build_plan(seed):
    rng = random.Random(seed)
    hide = {}
    catch = {}
    hops = set()
    for depth in range(200):
        hide[depth] = rng.choice(_HIDE_CHOICES)
        r = rng.random()
        if r < 0.12:
            catch[depth] = "context"
        elif r < 0.20:
            catch[depth] = "cause"
        elif r < 0.25:
            catch[depth] = "none"
        if rng.random() < 0.3:
            hops.add(depth)
    return hide, catch, hops


def _hop(n, depth, plan):
    marker = n ^ depth  # noqa: F841
    return _walk(n, depth, plan)


def _walk(n, depth, plan):
    hide, catch, hops = plan
    __traceback_hide__ = hide[depth]  # noqa: F841
    if n == 1:
        raise LookupError(f"bottom reached at depth {depth}")
    nxt = n // 2 if n % 2 == 0 else 3 * n + 1
    step = _hop if depth in hops else _walk
    mode = catch.get(depth)
    if mode is None:
        return step(nxt, depth + 1, plan)
    try:
        return step(nxt, depth + 1, plan)
    except LookupError as e:
        if mode == "context":
            raise LookupError(f"wrapped at {depth}")
        if mode == "cause":
            raise KeyError(depth) from e
        raise IndexError(depth) from None


class TestProcessTracebackLoops(unittest.TestCase):
    def test_chained_collatz_traceback(self):
        seed_value = sum(ord(c) for c in "werkzeug") // 13
        plan = _build_plan(seed_value * 7)
        start = 3 ** 3
        try:
            _walk(start, 0, plan)
        except LookupError as exc:
            te = _process_traceback(exc, skip=1)

        chain = []
        node = te
        while node is not None:
            chain.append(node)
            node = node.__cause__ or node.__context__
        self.assertGreater(len(chain), 1)
        for item in chain:
            for frame in item.stack:
                self.assertTrue(hasattr(frame, "local_ns"))
        self.assertTrue(any(fs.name == "_walk" for item in chain for fs in item.stack))
