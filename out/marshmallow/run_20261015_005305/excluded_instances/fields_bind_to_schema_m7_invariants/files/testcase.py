import random
import unittest

from marshmallow import Schema, fields
from marshmallow.fields import Tuple

LEAF_CLASSES = [
    fields.String,
    fields.Integer,
    fields.Float,
    fields.Boolean,
    fields.Raw,
    fields.Email,
    fields.DateTime,
]


class HostSchema(Schema):
    pass


def make_leaf(rng):
    cls = rng.choice(LEAF_CLASSES)
    mode = rng.randrange(4)
    if mode == 0:
        return cls  # resolved to a fresh default instance by Tuple.__init__
    if mode == 1:
        return cls(required=True)
    if mode == 2:
        return cls(load_default=None)
    return cls(allow_none=rng.random() < 0.5)


def make_tuple(rng, depth, lo, hi, nest_prob=0.35, **kwargs):
    elems = []
    for _ in range(rng.randint(lo, hi)):
        if depth > 0 and rng.random() < nest_prob:
            inner_kwargs = {"required": True} if rng.random() < 0.4 else {}
            elems.append(make_tuple(rng, depth - 1, lo, hi, nest_prob, **inner_kwargs))
        else:
            elems.append(make_leaf(rng))
    return Tuple(elems, **kwargs)


def walk(field):
    yield field
    if isinstance(field, Tuple):
        for child in field.tuple_fields:
            yield from walk(child)


class TupleBindInvariantTest(unittest.TestCase):
    def check_bound(self, tup, name):
        for child in tup.tuple_fields:
            self.assertIs(child.parent, tup)
            if isinstance(child, Tuple):
                self.check_bound(child, name)
        self.assertEqual(len(tup.validate_length.equal and tup.tuple_fields or []),
                         tup.validate_length.equal)

    def test_flat_random_leaves(self):
        rng = random.Random(11)
        tup = make_tuple(rng, 0, 6, 6)
        tup._bind_to_schema("alpha", HostSchema())
        self.check_bound(tup, "alpha")
        self.assertEqual(tup.name, "alpha")

    def test_nested_depth_two(self):
        rng = random.Random(1)
        tup = make_tuple(rng, 2, 2, 5)
        tup._bind_to_schema("beta", HostSchema())
        self.check_bound(tup, "beta")

    def test_nested_depth_three_narrow(self):
        rng = random.Random(2)
        tup = make_tuple(rng, 3, 1, 3, nest_prob=0.6, required=True)
        tup._bind_to_schema("gamma", HostSchema())
        self.check_bound(tup, "gamma")

    def test_single_underscored_name(self):
        rng = random.Random(4)
        tup = Tuple([make_leaf(rng) for _ in range(3)])
        tup._bind_to_schema("_".join(["row", "id"]), HostSchema())
        self.check_bound(tup, tup.name)

    def test_empty_tuple(self):
        tup = Tuple(())
        tup._bind_to_schema("empty", HostSchema())
        self.assertEqual(tup.tuple_fields, [])

    def test_rebind_twice(self):
        rng = random.Random(5)
        tup = make_tuple(rng, 1, 2, 4, nest_prob=0.5)
        tup._bind_to_schema("first", HostSchema())
        tup._bind_to_schema("second", HostSchema())
        self.assertEqual(tup.name, "first")
        self.assertTrue(all(child.parent is tup for child in tup.tuple_fields))

    def test_list_field_parent(self):
        rng = random.Random(6)
        tup = make_tuple(rng, 1, 3, 4)
        parent = fields.List(fields.String())
        parent._bind_to_schema("host", HostSchema())
        tup._bind_to_schema("listed", parent)
        self.assertIs(tup.parent, parent)
        self.check_bound(tup, "listed")

    def test_tuple_field_parent(self):
        rng = random.Random(7)
        outer = Tuple([fields.Integer(), fields.String()])
        outer._bind_to_schema("outer", HostSchema())
        tup = make_tuple(rng, 1, 2, 5, nest_prob=0.4)
        tup._bind_to_schema("inner", outer)
        self.assertIs(tup.parent, outer)
        self.check_bound(tup, "inner")

    def test_classes_only(self):
        rng = random.Random(8)
        inner = Tuple([rng.choice(LEAF_CLASSES) for _ in range(rng.randint(3, 5))])
        elems = [rng.choice(LEAF_CLASSES) for _ in range(6)]
        elems.insert(rng.randrange(len(elems) + 1), inner)
        tup = Tuple(elems)
        tup._bind_to_schema("classy", HostSchema())
        self.check_bound(tup, "classy")

    def test_many_small_tuples(self):
        rng = random.Random(9)
        host = HostSchema()
        tuples = [make_tuple(rng, 1, 1, 3, nest_prob=0.3) for _ in range(5)]
        for idx, tup in enumerate(tuples):
            tup._bind_to_schema("col" + "x" * idx, host)
            self.check_bound(tup, tup.name)

    def test_deep_chain(self):
        node = Tuple([fields.String(required=True), fields.Integer(load_default=None)])
        for level in range(4):
            extra = [fields.Float(allow_none=bool(level % 2))] * (level % 3)
            node = Tuple([node, *extra], required=level % 2 == 0)
        node._bind_to_schema("chain", HostSchema())
        self.check_bound(node, "chain")
        self.assertEqual(sum(1 for f in walk(node) if isinstance(f, Tuple)), 5)

    def test_load_default_mix(self):
        rng = random.Random(3)
        tup = make_tuple(rng, 1, 4, 6, nest_prob=0.25, load_default=None)
        tup._bind_to_schema("mixed", HostSchema())
        self.assertTrue(tup.allow_none)
        self.check_bound(tup, "mixed")


if __name__ == "__main__":
    unittest.main()
