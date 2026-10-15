import random
import unittest

from marshmallow import Schema, fields
from marshmallow.experimental.context import Context


def _tag(obj):
    # Only odd values consult the context; the default depends on the value.
    if obj["v"] % 2:
        fallback = ... if obj["v"] % 3 == 0 else {"d": -1}
        try:
            return Context.get(fallback)["d"] + obj["v"]
        except LookupError:
            return -obj["v"]
    return obj["v"]


class RowSchema(Schema):
    tag = fields.Function(_tag)


def _children(rng, seed, depth):
    count = (seed * 7 + depth) % 4 + 1
    return [rng.randrange(0, 97) for _ in range(count)]


def _walk(rng, depth, seeds, log):
    for seed in seeds:
        kind = seed % 5
        if kind == 0 and depth < 3:
            with Context({"d": depth, "s": seed}):
                log.append(("enter", Context.get()["d"]))
                _walk(rng, depth + 1, _children(rng, seed, depth), log)
        elif kind == 1:
            current = Context.get(None)
            log.append(("peek", None if current is None else current["s"]))
        elif kind == 2:
            try:
                log.append(("strict", Context.get(...)["s"]))
            except LookupError:
                log.append(("strict", "missing"))
        elif kind == 3:
            rows = [{"v": (seed + i * depth) % 11} for i in range(seed % 3 + 1)]
            log.append(("dump", sum(r["tag"] for r in RowSchema(many=True).dump(rows))))
        else:
            unused = Context({"d": seed})
            log.append(("built", unused.token))


class TestContextGetCalls(unittest.TestCase):
    def test_nested_context_lookups(self):
        rng = random.Random(918273)
        seeds = [rng.randrange(0, 97) for _ in range(14)]
        # Make sure the walk opens at least a few nested scopes.
        seeds[3] = 5 * (seeds[3] // 5)
        seeds[9] = 5 * (seeds[9] // 5)
        log = []
        _walk(rng, 0, seeds, log)

        kinds = {k for k, _ in log}
        self.assertTrue({"enter", "peek", "strict", "dump"} <= kinds)
        self.assertGreater(len(log), 20)
        self.assertIn(("strict", "missing"), log)
        with self.assertRaises(LookupError):
            Context.get()
