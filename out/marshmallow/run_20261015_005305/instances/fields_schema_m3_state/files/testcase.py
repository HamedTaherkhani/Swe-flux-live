import random
import unittest

from marshmallow import Schema, fields
from marshmallow.fields import Nested

SYLLABLES = ["ka", "lo", "mi", "ru", "te", "zo", "pa", "ne", "vu", "sh"]


def make_names(seed, count):
    rng = random.Random(seed)
    names = []
    while len(names) < count:
        name = "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3)))
        if name not in names:
            names.append(name)
    return names


def make_schema_class(seed, count):
    names = make_names(seed, count)
    return Schema.from_dict({n: fields.Raw() for n in names}), names


def pick(names, seed, k):
    rng = random.Random(seed * 7 + 3)
    return rng.sample(names, k)


class ZetaRegistered(Schema):
    alpha = fields.Int()
    beta = fields.Str()
    gamma = fields.Raw()


class TestNestedSchemaState(unittest.TestCase):
    def access(self, field, times):
        first = field.schema
        for _ in range(times):
            self.assertIs(field.schema, first)
        return first

    def test_instance_plain_nested_only(self):
        cls, names = make_schema_class(11, 7)
        field = Nested(cls(), only=pick(names, 1, 4) + ["missing"])
        s = self.access(field, 3)
        self.assertEqual(len(s.fields), 4)

    def test_instance_only_nested_only(self):
        cls, names = make_schema_class(12, 8)
        inner_only = pick(names, 2, 5)
        outer_only = pick(names, 3, 5)
        field = Nested(cls(only=inner_only), only=outer_only)
        s = self.access(field, 4)
        self.assertEqual(
            set(s.fields), set(inner_only) & set(outer_only)
        )

    def test_instance_exclude_nested_exclude(self):
        cls, names = make_schema_class(13, 9)
        field = Nested(
            cls(exclude=pick(names, 4, 1)), exclude=pick(names, 5, 2)
        )
        s = self.access(field, 2)
        self.assertGreaterEqual(len(s.fields), 4)

    def test_instance_no_exclude_nested_exclude(self):
        cls, names = make_schema_class(14, 5)
        field = Nested(cls(), exclude=names[1::2])
        s = self.access(field, 5)
        self.assertEqual(len(s.fields), 3)

    def test_both_options_with_partial_instance(self):
        cls, names = make_schema_class(15, 10)
        inst = cls(exclude=pick(names, 6, 1))
        field = Nested(inst, only=pick(names, 7, 6), exclude=pick(names, 8, 3))
        s = self.access(field, 3)
        self.assertLessEqual(len(s.fields), 6)

    def test_callable_returning_instance_many(self):
        cls, names = make_schema_class(16, 6)
        field = Nested(
            lambda: cls(only=names[::-1][:4]), only=names[2:], many=True
        )
        s = self.access(field, 2)
        self.assertTrue(s.many)

    def test_invalid_exclude_raises(self):
        cls, names = make_schema_class(17, 4)
        field = Nested(cls(only=names[:3]), exclude=[names[0], "nothere"])
        with self.assertRaises(ValueError):
            field.schema
        self.assertIsInstance(self.access(field, 2), Schema)

    def test_schema_class_path(self):
        cls, names = make_schema_class(18, 6)
        field = Nested(cls, only=pick(names, 9, 3), many=True)
        s = self.access(field, 6)
        self.assertEqual(len(s.fields), 3)

    def test_registry_string_path(self):
        field = Nested("ZetaRegistered", exclude=("beta",))
        s = self.access(field, 4)
        self.assertNotIn("beta", s.fields)

    def test_dict_path(self):
        names = make_names(19, 5)
        field = Nested({n: fields.Int() for n in names}, only=names[:2])
        s = self.access(field, 3)
        self.assertEqual(len(s.fields), 2)

    def test_bad_nested_type(self):
        field = Nested(42)
        with self.assertRaisesRegex(ValueError, "must be passed"):
            field.schema

    def test_chained_instance_copy(self):
        cls, names = make_schema_class(20, 9)
        first = Nested(cls(only=pick(names, 10, 7)), exclude=pick(names, 11, 2))
        base = self.access(first, 2)
        second = Nested(base, only=pick(names, 12, 6), exclude=[names[-1]])
        s = self.access(second, 3)
        self.assertLessEqual(len(s.fields), len(base.fields))
