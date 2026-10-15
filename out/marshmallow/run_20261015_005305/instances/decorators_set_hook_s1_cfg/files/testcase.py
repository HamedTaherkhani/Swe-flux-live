import random
import unittest

from marshmallow import Schema, fields
from marshmallow import decorators as dec


FIELD_NAMES = ["f%d" % k for k in range(6)]

# (decorator name, may be applied bare without parentheses)
POOL = [
    ("pre_dump", True),
    ("post_dump", True),
    ("pre_load", True),
    ("post_load", True),
    ("validates_schema", True),
    ("validates", False),
]


def make_hook(idx):
    # Pass-through: valid as a processor, harmless as a validator.
    def hook(self, data, **kwargs):
        return data

    hook.__name__ = "hook_%d" % idx
    return hook


class HookRegistrationTest(unittest.TestCase):
    def test_generated_schema_hooks(self):
        rng = random.Random(4242)
        attrs = {name: fields.Raw() for name in FIELD_NAMES}
        expected = {}
        muted_count = 0

        for idx in range(14):
            n_decos = rng.choice([1, 1, 2, 3])
            plan = [rng.choice(POOL) for _ in range(n_decos)]
            fn = make_hook(idx)
            muted = rng.random() < 0.2
            if muted:
                fn.__marshmallow_hook__ = None
                muted_count += 1

            for name, bare_ok in plan:
                deco = getattr(dec, name)
                if name == "validates":
                    picked = rng.sample(FIELD_NAMES, rng.randint(1, 2))
                    fn = deco(*picked)(fn)
                elif bare_ok and rng.random() < 0.5:
                    fn = deco(fn)
                else:
                    fn = deco(pass_collection=rng.random() < 0.3)(fn)
                if not muted:
                    expected[name] = expected.get(name, 0) + 1
            if muted:
                # A None hook config is never registered and would break
                # SchemaMeta.resolve_hooks, so keep it out of the class body.
                self.assertIsNone(fn.__marshmallow_hook__)
            else:
                attrs["m_%d" % idx] = fn

        GenSchema = type("GenSchema", (Schema,), attrs)
        got = {tag: len(v) for tag, v in GenSchema._hooks.items() if v}
        self.assertEqual(got, expected)
        self.assertGreater(muted_count, 0)

        payload = {name: k for k, name in enumerate(FIELD_NAMES)}
        loaded = GenSchema().load(payload)
        self.assertEqual(sorted(loaded), sorted(FIELD_NAMES))
        self.assertEqual(GenSchema().dump(payload), payload)
