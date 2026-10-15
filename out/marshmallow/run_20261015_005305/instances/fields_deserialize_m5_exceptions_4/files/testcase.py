import random
import unittest
from decimal import Decimal
from fractions import Fraction

from marshmallow import fields


def drive(field, values):
    """Feed every value to Boolean._deserialize; record outcomes generically."""
    outcomes = []
    for value in values:
        try:
            outcomes.append(("ok", field._deserialize(value, "flag", None)))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(("err", exc))
    return outcomes


def summary(outcomes):
    trues = sum(1 for kind, v in outcomes if kind == "ok" and v is True)
    falses = sum(1 for kind, v in outcomes if kind == "ok" and v is False)
    errs = [v for kind, v in outcomes if kind == "err"]
    return trues, falses, errs


def is_field_error(exc):
    return hasattr(exc, "messages") and hasattr(exc, "normalized_messages")


class HashProbe:
    """Hash derived from int(label); equality compares against `match`."""

    def __init__(self, label, match):
        self.label = label
        self.match = match

    def __hash__(self):
        return int(self.label) % 3

    def __eq__(self, other):
        return self.match == other


class EqProbe:
    table = {"a": 0, "b": "zz", "c": None, "d": 1.5}

    def __init__(self, h, key):
        self.h = h
        self.key = key

    def __hash__(self):
        return self.h

    def __eq__(self, other):
        return self.table[self.key] < other


class Shy:
    def __init__(self, name, weight, code=None):
        self.name = name
        self.weight = weight
        if code is not None:
            self.code = code

    def __hash__(self):
        try:
            return self.code
        except AttributeError:
            return len(self.name) % 2

    def __eq__(self, other):
        return self.weight == other


class Gauge:
    def __init__(self, n, k):
        self.n = n
        self.k = k

    def __bool__(self):
        return (100 // (self.n - self.k)) > 3


class Loud:
    def __init__(self, tag):
        self.tag = tag

    def __str__(self):
        return "loud-%d" % self.tag


class LoudUnhashable(Loud):
    __hash__ = None


class TestBooleanDeserializeExceptions(unittest.TestCase):
    def test_canonical_tokens_shuffled(self):
        field = fields.Boolean()
        rng = random.Random(101)
        pool = sorted(field.truthy, key=repr) + sorted(field.falsy, key=repr)
        values = [rng.choice(pool) for _ in range(34)]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(errs, [])
        self.assertEqual(trues + falses, len(values))

    def test_random_case_words(self):
        field = fields.Boolean()
        rng = random.Random(202)
        words = ["true", "false", "yes", "no", "on", "off", "t", "y"]
        values = []
        for _ in range(40):
            w = rng.choice(words)
            values.append("".join(c.upper() if rng.random() < 0.5 else c for c in w))
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(errs)
        self.assertTrue(all(is_field_error(e) for e in errs))

    def test_numeric_spectrum(self):
        field = fields.Boolean()
        values = [i - 3 for i in range(9)]
        values += [x / 2 for x in range(-2, 5)]
        values += [complex(i % 2, 0) for i in range(3)] + [complex(0, 1)]
        values += [True, False]
        trues, falses, errs = summary(drive(field, values))
        self.assertGreater(trues, 0)
        self.assertGreater(falses, 0)
        self.assertEqual(trues + falses + len(errs), len(values))

    def test_unhashable_containers(self):
        field = fields.Boolean()
        rng = random.Random(303)
        values = []
        for i in range(18):
            r = rng.randrange(4)
            if r == 0:
                values.append([rng.randint(0, 1) for _ in range(i % 3)])
            elif r == 1:
                values.append({str(i): i})
            elif r == 2:
                values.append({i, i + 1})
            else:
                values.append(bytearray(b"true"[: i % 5]))
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses, 0)
        self.assertEqual(len(errs), len(values))
        self.assertTrue(any(e.__cause__ is not None for e in errs))

    def test_hash_from_label(self):
        field = fields.Boolean()
        rng = random.Random(404)
        labels = ["7", " 4", "0x3", "+5", "1_0", "٣", "two", "12", "-8", "3.0", "", "05"]
        values = [HashProbe(rng.choice(labels), rng.choice([0, 1, "1"])) for _ in range(26)]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(any(not is_field_error(e) for e in errs))

    def test_equality_that_misbehaves(self):
        field = fields.Boolean()
        rng = random.Random(505)
        values = [EqProbe(rng.choice([0, 1, 2]), rng.choice("abcdef")) for _ in range(30)]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(any(is_field_error(e) for e in errs))
        self.assertTrue(any(not is_field_error(e) for e in errs))

    def test_shy_hash_fallback(self):
        field = fields.Boolean()
        rng = random.Random(606)
        names = ["a", "bb", "ccc", "dddd"]
        values = []
        for i in range(20):
            code = rng.choice([None, None, 0, 1, 2])
            values.append(Shy(rng.choice(names), rng.choice([0, 1, 1.0, "1"]), code))
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(all(is_field_error(e) for e in errs))

    def test_empty_truthy_uses_bool(self):
        field = fields.Boolean(truthy=[])
        rng = random.Random(707)
        values = [Gauge(rng.randint(0, 5), rng.randint(0, 5)) for _ in range(24)]
        values += ["", "no", 0, [], [0], None]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(errs)

    def test_custom_square_sets(self):
        field = fields.Boolean(
            truthy=[i * i for i in range(1, 6)], falsy=[i * i + 1 for i in range(0, 5)]
        )
        rng = random.Random(808)
        values = []
        for _ in range(28):
            r = rng.randrange(5)
            n = rng.randint(0, 26)
            if r == 0:
                values.append([n])
            elif r == 1:
                values.append(float(n))
            elif r == 2:
                values.append(str(n))
            else:
                values.append(n)
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertGreater(trues + falses, 0)

    def test_message_formats_input_with_str(self):
        field = fields.Boolean(error_messages={"invalid": "{input!s} rejected"})
        rng = random.Random(909)
        values = []
        for i in range(22):
            tag = rng.choice([i, str(i), i * 2])
            cls = LoudUnhashable if rng.random() < 0.4 else Loud
            values.append(cls(tag))
        values += ["maybe", "on"]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(any(is_field_error(e) for e in errs))
        self.assertTrue(any(not is_field_error(e) for e in errs))

    def test_message_indexes_input(self):
        field = fields.Boolean(error_messages={"invalid": "first={input[0]}"})
        rng = random.Random(1010)
        values = []
        for i in range(24):
            r = rng.randrange(6)
            if r == 0:
                values.append("")
            elif r == 1:
                values.append("x" * (i % 3))
            elif r == 2:
                values.append([i] * (i % 2))
            elif r == 3:
                values.append({0: i} if i % 2 else {})
            elif r == 4:
                values.append(tuple(range(i % 3)))
            else:
                values.append(str(i % 2))
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertTrue(any(not is_field_error(e) for e in errs))

    def test_odd_hashables(self):
        field = fields.Boolean()
        values = [None, b"true", b"1", (1,), (), frozenset({1}), (1, [2]), ("t", ["f"])]
        values += [Decimal("1"), Decimal("0.0"), Decimal("1.5"), Decimal("sNaN"), Decimal("NaN")]
        values += [Fraction(2, 2), Fraction(1, 2), Decimal("-sNaN")]
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertGreater(trues, 0)

    def test_custom_word_sets_with_noise(self):
        rng = random.Random(1111)
        letters = "abcde"
        truthy = ["".join(rng.choice(letters) for _ in range(2)) for _ in range(6)]
        falsy = ["".join(rng.choice(letters) for _ in range(2)) for _ in range(6)]
        field = fields.Boolean(truthy=truthy, falsy=falsy)
        values = []
        for i in range(30):
            word = "".join(rng.choice(letters) for _ in range(2))
            values.append(word if i % 7 else [word])
        trues, falses, errs = summary(drive(field, values))
        self.assertEqual(trues + falses + len(errs), len(values))
        self.assertGreater(trues + falses, 0)


if __name__ == "__main__":
    unittest.main()
