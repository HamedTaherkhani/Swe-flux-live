import decimal
import fractions
import random
import unittest

from marshmallow import fields
from marshmallow.fields import Number

TARGET = Number._validated


class FractionNumber(Number):
    num_type = fractions.Fraction


def _lenient(value):
    """Parse a value leniently; parsing problems are absorbed here."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return round(float(value), 1)
    except ValueError:
        return -1


class LenientNumber(Number):
    num_type = staticmethod(_lenient)


_TABLE = {k: k * k for k in range(0, 40, 3)}


def _lookup(value):
    return _TABLE[value]


class LookupNumber(Number):
    num_type = staticmethod(_lookup)


def _run(field, values):
    ok, failed = [], 0
    for v in values:
        try:
            ok.append(TARGET(field, v))
        except Exception:
            failed += 1
    return ok, failed


class TestNumberValidatedExceptions(unittest.TestCase):
    def test_integer_mixed_strings(self):
        rng = random.Random(11)
        values = []
        for _ in range(18):
            r = rng.random()
            if r < 0.4:
                values.append(str(rng.randint(-50, 50)))
            elif r < 0.7:
                values.append("".join(rng.choice("0123x") for _ in range(3)))
            else:
                values.append(rng.choice([True, False, None]))
        ok, failed = _run(fields.Integer(), values)
        self.assertEqual(len(ok) + failed, len(values))
        self.assertTrue(all(isinstance(x, int) for x in ok))

    def test_integer_special_floats(self):
        rng = random.Random(23)
        pool = [float("inf"), float("-inf"), float("nan"), 1e300, -2.5]
        values = [rng.choice(pool) * (1 if i % 3 else 1.0) for i in range(14)]
        ok, failed = _run(fields.Integer(), values)
        self.assertEqual(len(ok) + failed, len(values))
        self.assertGreater(failed, 0)

    def test_float_clean_inputs(self):
        rng = random.Random(5)
        values = [rng.uniform(-100, 100) for _ in range(12)]
        values += [str(rng.randint(0, 9)) + "." + str(rng.randint(0, 99)) for _ in range(6)]
        ok, failed = _run(fields.Float(), values)
        self.assertEqual(failed, 0)
        self.assertEqual(len(ok), len(values))

    def test_float_huge_ints(self):
        values = [10 ** (k * 70) for k in range(1, 9)] + [k * 1.5 for k in range(4)]
        ok, failed = _run(fields.Float(), values)
        self.assertEqual(len(ok) + failed, len(values))
        self.assertGreater(len(ok), 0)

    def test_decimal_unquantized(self):
        rng = random.Random(77)
        values = []
        for _ in range(16):
            r = rng.random()
            if r < 0.5:
                values.append(round(rng.uniform(-10, 10), 3))
            elif r < 0.75:
                values.append(rng.choice(["1e5", "abc", "NaN", "--1", "0x10"]))
            else:
                values.append(rng.choice([True, None, [1]]))
        ok, failed = _run(fields.Decimal(), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_decimal_quantized(self):
        rng = random.Random(3)
        values = [str(rng.randint(1, 9)) + "e" + str(rng.choice([1, 5, 30, 40])) for _ in range(10)]
        values += [str(round(rng.random(), 5)) for _ in range(4)]
        ok, failed = _run(fields.Decimal(places=2), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_fraction_strings(self):
        rng = random.Random(41)
        values = []
        for _ in range(15):
            a, b = rng.randint(-3, 9), rng.randint(0, 4)
            values.append(f"{a}/{b}" if rng.random() < 0.7 else f"{a}//{b}")
        ok, failed = _run(FractionNumber(), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_fraction_floats_and_objects(self):
        rng = random.Random(8)
        pool = [0.25, float("inf"), float("nan"), None, 3, (1, 2), False]
        values = [rng.choice(pool) for _ in range(13)]
        ok, failed = _run(FractionNumber(), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_lenient_absorbs_parse_errors(self):
        rng = random.Random(19)
        values = ["".join(rng.choice("12.ab") for _ in range(rng.randint(1, 4))) for _ in range(15)]
        values += [rng.choice([None, [], True])]
        ok, failed = _run(LenientNumber(), values)
        self.assertEqual(len(ok) + failed, len(values))
        self.assertGreater(len(ok), 0)

    def test_lookup_table(self):
        rng = random.Random(29)
        values = [rng.randint(0, 20) for _ in range(14)] + [[3], {"k": 1}]
        ok, failed = _run(LookupNumber(), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_missing_message_key(self):
        field = fields.Integer()
        field.error_messages = {
            k: v for k, v in field.error_messages.items() if k != "too_large"
        }
        rng = random.Random(61)
        pool = [float("inf"), "12", "x", 1e400, -7.9, None]
        values = [rng.choice(pool) for _ in range(15)]
        ok, failed = _run(field, values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_broken_message_templates(self):
        field = fields.Integer(
            error_messages={"invalid": "bad {input:d}", "too_large": "{limit} exceeded"}
        )
        rng = random.Random(97)
        pool = ["q", True, float("nan"), float("-inf"), 4.0, "8", None, False]
        values = [rng.choice(pool) for _ in range(17)]
        ok, failed = _run(field, values)
        self.assertEqual(len(ok) + failed, len(values))


if __name__ == "__main__":
    unittest.main()
