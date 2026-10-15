"""Deterministic scenarios that drive Schema._init_fields directly."""

import random
import unittest

from marshmallow import Schema, fields

KINDS = [fields.String, fields.Integer, fields.Float, fields.Boolean, fields.Date]


def make_fields(rng, count, prefix):
    """Build ``count`` fields with seeded load_only / dump_only flags."""
    out = {}
    for i in range(count):
        kind = rng.choice(KINDS)
        roll = rng.random()
        kwargs = {}
        if roll < 0.2:
            kwargs["load_only"] = True
        elif roll < 0.4:
            kwargs["dump_only"] = True
        out[f"{prefix}{i:02d}"] = kind(**kwargs)
    return out


def make_schema_class(seed, count, prefix="f", base=Schema, name="Gen"):
    rng = random.Random(seed)
    return base.from_dict(make_fields(rng, count, prefix), name=name)


class BindLimitSchema(Schema):
    """Raises from on_bind_field once more than ``bind_limit`` fields were bound."""

    bind_limit = 0

    def on_bind_field(self, field_name, field_obj):
        self.bound = getattr(self, "bound", 0) + 1
        if self.bound > self.bind_limit:
            raise RuntimeError("bind limit reached")


class TestInitFieldsLoops(unittest.TestCase):
    def test_01_plain_reinit(self):
        cls = make_schema_class(seed=11, count=7 * 3 + 2)
        s = cls()
        s._init_fields()
        self.assertEqual(len(s.fields), len(s.declared_fields))
        self.assertLessEqual(len(s.dump_fields), len(s.fields))

    def test_02_only_random_subset(self):
        rng = random.Random(202)
        cls = make_schema_class(seed=22, count=18 + rng.randrange(4, 16))
        s = cls()
        names = sorted(s.declared_fields)
        s.only = s.set_class(n for n in names if rng.random() < 0.45)
        s._init_fields()
        self.assertEqual(set(s.fields), set(s.only))

    def test_03_exclude_by_parity(self):
        cls = make_schema_class(seed=33, count=4 * 4 + 1)
        names = sorted(cls._declared_fields)
        excl = [n for i, n in enumerate(names) if (i * 7) % 3 == 0]
        s = cls(exclude=excl)
        s.exclude = s.exclude | s.set_class(names[1:4])
        s._init_fields()
        self.assertTrue(set(s.fields).isdisjoint(s.exclude))

    def test_04_only_and_exclude_shrinking(self):
        cls = make_schema_class(seed=44, count=3 * 9)
        names = sorted(cls._declared_fields)
        s = cls(only=names[::2])
        for step in range(1, 4):
            s.exclude = s.set_class(names[: step * 3])
            s._init_fields()
        self.assertNotIn(names[0], s.fields)

    def test_05_meta_fields_option(self):
        rng = random.Random(55)
        flds = make_fields(rng, 6 * 4, "m")
        picked = tuple(sorted(n for n in flds if rng.random() < 0.6))

        class Meta:
            fields = picked

        cls = type("MetaFieldsSchema", (Schema,), {**flds, "Meta": Meta})
        s = cls()
        s.only = s.set_class(picked[: len(picked) // 2])
        s._init_fields()
        self.assertEqual(len(s.fields), len(picked) // 2)

    def test_06_bind_limit_raises_early(self):
        rng = random.Random(66)
        flds = make_fields(rng, 3 * 5, "b")
        limit = sum(1 for _ in range(12) if rng.random() < 0.5)
        cls = type("LimitedSchema", (BindLimitSchema,), {**flds, "bind_limit": 10**6})
        s = cls()
        s.bound = 0
        s.bind_limit = limit
        with self.assertRaises(RuntimeError):
            s._init_fields()
        self.assertEqual(s.bound, limit + 1)

    def test_07_data_key_collision(self):
        rng = random.Random(77)
        flds = make_fields(rng, 2 * 7, "d")
        victim = sorted(flds)[rng.randrange(len(flds))]
        cls = Schema.from_dict(flds, name="Collide")
        s = cls()
        for name, fobj in s.declared_fields.items():
            if name != victim:
                fobj.load_only = False
        s.declared_fields[victim].data_key = sorted(flds)[0] if victim != sorted(flds)[0] else sorted(flds)[1]
        s.declared_fields[victim].load_only = False
        s.declared_fields[sorted(flds)[0]].load_only = False
        s.declared_fields[sorted(flds)[1]].load_only = False
        with self.assertRaisesRegex(ValueError, "collides"):
            s._init_fields()

    def test_08_attribute_collision(self):
        rng = random.Random(88)
        flds = {f"a{i:02d}": fields.String() for i in range(3 * 3 + rng.randrange(1, 8))}
        cls = Schema.from_dict(flds, name="AttrCollide")
        s = cls()
        keys = sorted(s.declared_fields)
        s.declared_fields[keys[-1]].attribute = keys[0]
        with self.assertRaisesRegex(ValueError, "attribute"):
            s._init_fields()

    def test_09_meta_load_dump_only(self):
        rng = random.Random(99)
        flds = {f"x{i:02d}": fields.Integer() for i in range(2 * 9 + 1)}
        names = sorted(flds)
        lo = tuple(n for n in names if rng.random() < 0.3)
        do = tuple(n for n in names if n not in lo and rng.random() < 0.3)

        class Meta:
            load_only = lo
            dump_only = do

        cls = type("MetaLDSchema", (Schema,), {**flds, "Meta": Meta})
        s = cls(exclude=names[-3:])
        s._init_fields()
        self.assertEqual(len(s.load_fields) + len(s.dump_fields),
                         2 * len(s.fields) - len(set(lo) & set(s.fields)) - len(set(do) & set(s.fields)))

    def test_10_nested_only_propagation(self):
        child_cls = make_schema_class(seed=1010, count=4 * 5, prefix="c", name="Child")
        child_names = sorted(child_cls._declared_fields)
        parent_flds = make_fields(random.Random(1011), 3, "p")
        parent_flds["child"] = fields.Nested(child_cls())
        parent_cls = Schema.from_dict(parent_flds, name="Parent")
        s = parent_cls(only=["child." + n for n in child_names[1::3]] + ["p00"])
        nested_schema = s.fields["child"].schema
        nested_schema._init_fields()
        self.assertEqual(len(nested_schema.fields), len(child_names[1::3]))

    def test_11_growing_only_windows(self):
        cls = make_schema_class(seed=1111, count=2 * 2 * 3)
        names = sorted(cls._declared_fields)
        s = cls(only=names[:1])
        total = 0
        for width in range(2, len(names) + 1, 3):
            s.only = s.set_class(names[-width:])
            s._init_fields()
            total += len(s.fields)
        self.assertGreater(total, len(names))

    def test_12_inherited_with_bind_limit(self):
        rng = random.Random(1212)
        base_flds = make_fields(rng, 3 * 3, "i")
        cls = type("InheritedLimited", (BindLimitSchema,), {**base_flds, "bind_limit": 10**6})
        sub = type("SubLimited", (cls,), make_fields(rng, 2 * 4, "j"))
        s = sub(exclude=[n for n in sorted(base_flds) if rng.random() < 0.4])
        s.bound = 0
        s.bind_limit = len(s.fields) - rng.randrange(1, 5)
        with self.assertRaises(RuntimeError):
            s._init_fields()
        self.assertLess(s.bind_limit, len(s.fields))
