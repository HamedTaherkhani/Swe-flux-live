import random
import unittest

from marshmallow.error_store import ErrorStore
from marshmallow.exceptions import SCHEMA

FIELDS = ["name", "email", "tags"]


def _build_message(rng, depth):
    """Build a nested error message (str, list or dict) from the seeded RNG."""
    kind = rng.choice([0, 1, 2, 2, 3]) if depth > 0 else 0
    if kind == 0:
        return "err-{}".format(rng.randrange(100))
    if kind == 1:
        return ["msg-{}".format(rng.randrange(100)) for _ in range(rng.randrange(1, 4))]
    if kind == 2:
        keys = rng.sample(FIELDS + [SCHEMA], rng.randrange(1, 4))
        return {k: _build_message(rng, depth - 1) for k in keys}
    return [_build_message(rng, depth - 1) for _ in range(rng.randrange(1, 3))]


class ErrorStoreMergeTest(unittest.TestCase):
    def test_store_many_errors(self):
        rng = random.Random(20240611)
        store = ErrorStore()
        calls = 0
        for step in range(24):
            messages = _build_message(rng, 2 + step % 2)
            mode = rng.randrange(3)
            if mode == 0:
                store.store_error(messages)
            elif mode == 1:
                store.store_error(messages, rng.choice(FIELDS))
            else:
                store.store_error(messages, rng.choice(FIELDS), index=rng.randrange(2))
            calls += 1
        self.assertEqual(calls, 24)
        self.assertIsInstance(store.errors, dict)
        self.assertTrue(store.errors)
