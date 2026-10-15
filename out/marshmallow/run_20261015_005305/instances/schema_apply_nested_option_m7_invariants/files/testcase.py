import random
import unittest

from marshmallow import Schema, fields

LEAF_KEYS = [f"k{i}" for i in range(8)]


class LeafSchema(Schema):
    k0 = fields.String()
    k1 = fields.String()
    k2 = fields.String()
    k3 = fields.String()
    k4 = fields.String()
    k5 = fields.String()
    k6 = fields.String()
    k7 = fields.String()


class MidSchema(Schema):
    a = fields.Nested(LeafSchema)
    b = fields.Nested(LeafSchema, only=("k0", "k1", "k2", "k3"))
    c = fields.List(fields.Nested(LeafSchema, only=("k2", "k4", "k6")))
    d = fields.Pluck(LeafSchema, "k5")
    g = fields.Dict(keys=fields.String(), values=fields.Nested(LeafSchema))
    n = fields.Integer()


class RootSchema(Schema):
    m1 = fields.Nested(MidSchema)
    m2 = fields.List(fields.Nested(MidSchema, only=("a", "b", "n")))
    m3 = fields.Nested(MidSchema)
    rid = fields.Integer()


class MetaExcludeRoot(RootSchema):
    class Meta:
        exclude = ("m1.a.k1", "m1.c.k4", "rid")


def make_leaf(rng):
    return {k: f"{k}-{rng.randint(0, 99)}" for k in LEAF_KEYS}


def make_mid(rng):
    return {
        "a": make_leaf(rng),
        "b": make_leaf(rng),
        "c": [make_leaf(rng) for _ in range(rng.randint(1, 3))],
        "d": make_leaf(rng),
        "g": {f"x{j}": make_leaf(rng) for j in range(rng.randint(1, 2))},
        "n": rng.randint(0, 500),
    }


def make_root(seed):
    rng = random.Random(seed)
    return {
        "m1": make_mid(rng),
        "m2": [make_mid(rng) for _ in range(2)],
        "m3": make_mid(rng),
        "rid": rng.randint(1, 9),
    }


class ApplyNestedOptionsInvariantTest(unittest.TestCase):
    def _dump(self, schema, seed):
        out = schema.dump(make_root(seed))
        self.assertIsInstance(out, dict)
        return out

    def test_only_even_leaf_keys_under_m1_a(self):
        only = [f"m1.a.{k}" for k in LEAF_KEYS[::2]] + ["m1.n"]
        out = self._dump(RootSchema(only=only), 1)
        self.assertEqual(set(out), {"m1"})
        self.assertEqual(len(out["m1"]["a"]), len(LEAF_KEYS) // 2)

    def test_only_intersects_restricted_b(self):
        only = [f"m1.b.{k}" for k in LEAF_KEYS if int(k[1]) % 3 != 1]
        out = self._dump(RootSchema(only=only), 2)
        self.assertEqual(set(out["m1"]), {"b"})
        self.assertTrue(set(out["m1"]["b"]) <= {"k0", "k1", "k2", "k3"})

    def test_only_partial_overlap_with_list_inner_only(self):
        only = [f"m1.c.{k}" for k in ("k1", "k4", "k7")] + ["rid"]
        out = self._dump(RootSchema(only=only), 3)
        self.assertTrue(all(len(item) == 1 for item in out["m1"]["c"]))

    def test_only_duplicate_paths(self):
        base = [f"m1.{p}.k{j}" for p in "ab" for j in range(3)]
        only = base + base[1::2] + ["m3.n", "m3.n"]
        out = self._dump(RootSchema(only=only), 4)
        self.assertEqual(sorted(out), ["m1", "m3"])

    def test_only_on_list_of_mid_with_inner_only(self):
        only = ["m2." + f for f in ("a.k0", "b.k1", "n", "d", "c.k2")]
        out = self._dump(RootSchema(only=only), 5)
        self.assertEqual(len(out["m2"]), 2)

    def test_only_pluck_mismatch(self):
        only = [f"m1.d.{k}" for k in LEAF_KEYS if k != "k5"][:3] + ["m3.d.k5"]
        schema = RootSchema(only=only)
        self.assertEqual(sorted(schema.fields), ["m1", "m3"])
        self.assertIsNotNone(schema.fields["m3"].schema)
        self.assertIsNotNone(schema.fields["m1"].schema)

    def test_exclude_deep_paths(self):
        exclude = [f"m1.{p}.k{j}" for p in "ab" for j in range(0, 8, 3)]
        exclude += ["m3.a.k7", "rid"]
        out = self._dump(RootSchema(exclude=exclude), 6)
        self.assertNotIn("rid", out)
        self.assertNotIn("k0", out["m1"]["a"])

    def test_exclude_via_meta_and_argument(self):
        exclude = [f"m3.c.k{j}" for j in (2, 6)] + ["m2.n"]
        out = self._dump(MetaExcludeRoot(exclude=exclude), 7)
        self.assertNotIn("rid", out)
        self.assertNotIn("n", out["m2"][0])

    def test_exclude_dict_values(self):
        exclude = [f"m1.g.k{j}" for j in range(5)] + [f"m3.b.k{j}" for j in range(1)]
        out = self._dump(RootSchema(exclude=exclude), 8)
        for leaf in out["m1"]["g"].values():
            self.assertEqual(len(leaf), 3)

    def test_only_and_exclude_combined(self):
        only = [f"m1.{p}" for p in "abn"] + ["m3.c.k4", "m3.c.k2", "m3.a.k1"]
        exclude = ["m1.a.k3", "m1.b.k0", "m3.a.k1"]
        out = self._dump(RootSchema(only=only, exclude=exclude), 9)
        self.assertNotIn("k3", out["m1"]["a"])

    def test_mid_schema_direct_only(self):
        rng = random.Random(23)
        picks = sorted(rng.sample(LEAF_KEYS, 5))
        only = [f"{p}.{k}" for p in ("a", "b", "c", "g") for k in picks]
        schema = MidSchema(only=only)
        out = schema.dump(make_mid(rng))
        self.assertEqual(sorted(out), ["a", "b", "c", "g"])

    def test_mid_schema_many_only_three_levels(self):
        only = [f"a.k{j}" for j in range(7, 0, -2)] + ["c.k6", "c.k0", "d.k5", "d.k5"]
        schema = MidSchema(only=only, many=True)
        rng = random.Random(11)
        out = schema.dump([make_mid(rng) for _ in range(3)])
        self.assertEqual(len(out), 3)
