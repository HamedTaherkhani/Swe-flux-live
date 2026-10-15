import random
import unittest

from marshmallow import Schema, fields
from marshmallow.decorators import (
    MarshmallowHook,
    post_load,
    pre_load,
    validates,
    validates_schema,
)

FIELD_NAMES = ["alpha", "beta", "gamma"]


def _make_pool(rng, size):
    """Build a pool of plain hook functions; some opt out of hook registration."""
    pool = []
    for idx in range(size):

        def hook(self, data, **kwargs):
            return data

        hook.__name__ = "hook_{}".format(idx)
        if rng.random() < 0.35:
            # Inherit the class-level ``None`` sentinel: set_hook must skip it.
            hook.__marshmallow_hook__ = MarshmallowHook.__marshmallow_hook__
        pool.append(hook)
    return pool


class ValidatesSchemaDecorationTest(unittest.TestCase):
    def test_decorate_pool(self):
        rng = random.Random(77031)
        pool = _make_pool(rng, 7)
        pending = []
        applied = 0
        direct_results = 0

        for step in range(22):
            fn = pool[rng.randrange(len(pool))]
            kind = rng.choice(["vs", "vs", "vs_factory", "pre", "post", "val"])
            if kind == "vs":
                result = validates_schema(fn)
                self.assertIs(result, fn)
                direct_results += 1
                applied += 1
            elif kind == "vs_factory":
                deco = validates_schema(
                    pass_collection=bool(step % 2),
                    pass_original=rng.random() < 0.5,
                    skip_on_field_errors=step % 3 != 0,
                )
                pending.append((deco, fn))
            elif kind == "pre":
                if rng.random() < 0.5:
                    pre_load(fn)
                    applied += 1
                else:
                    pending.append((pre_load(pass_collection=True), fn))
            elif kind == "post":
                pending.append((post_load(pass_original=True), fn))
            else:
                names = rng.sample(FIELD_NAMES, rng.randrange(1, 3))
                pending.append((validates(*names), fn))

            # Flush deferred decorators (LIFO) whenever enough have piled up.
            if len(pending) >= 3 or (pending and step % 5 == 4):
                while pending:
                    deco, target = pending.pop()
                    self.assertIs(deco(target), target)
                    applied += 1

        while pending:
            deco, target = pending.pop()
            deco(target)
            applied += 1

        registered = 0
        for fn in pool:
            cfg = fn.__marshmallow_hook__
            if cfg is not None:
                registered += sum(len(v) for v in cfg.values())
        self.assertGreater(applied, registered)
        self.assertGreater(direct_results, 0)

        # Sanity check: a decorated method still works inside a real Schema.
        checked = []

        class Probe(Schema):
            alpha = fields.Int()

            @validates_schema(pass_original=True)
            def check(self, data, original, **kwargs):
                checked.append((data["alpha"], original["alpha"]))

        Probe().load({"alpha": "5"})
        self.assertEqual(len(checked), 1)
