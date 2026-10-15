import decimal
import random
import unittest

from marshmallow import ValidationError, fields


def _run(field, values):
    ok, bad = [], []
    for v in values:
        try:
            ok.append(field._validated(v))
        except ValidationError as err:
            bad.append(err)
    return ok, bad


def _num_strings(rng, n, lo=-500, hi=500, scale=3):
    out = []
    for _ in range(n):
        whole = rng.randint(lo, hi)
        frac = rng.randint(0, 10**scale - 1)
        out.append(f"{whole}.{frac:0{scale}d}")
    return out


SPECIALS = ["nan", "-Infinity", "inf", "sNaN", "-nan", "Infinity"]
JUNK = ["abc", "1.2.3", "", "12e", "--4", "0x1F"]


class TestDecimalValidated(unittest.TestCase):
    def test_01_plain_strings(self):
        rng = random.Random(101)
        field = fields.Decimal()
        values = _num_strings(rng, rng.randint(14, 22))
        ok, bad = _run(field, values)
        self.assertEqual(len(ok) + len(bad), len(values))
        self.assertTrue(all(isinstance(x, decimal.Decimal) for x in ok))

    def test_02_specials_rejected_and_allowed(self):
        rng = random.Random(202)
        strict = fields.Decimal()
        lax = fields.Decimal(allow_nan=True)
        pool = [rng.choice(SPECIALS) for _ in range(rng.randint(8, 13))]
        _, bad_strict = _run(strict, pool)
        ok_lax, _ = _run(lax, pool[: len(pool) // 2 + rng.randint(0, 3)])
        self.assertTrue(bad_strict)
        self.assertTrue(ok_lax)

    def test_03_booleans_mixed(self):
        rng = random.Random(303)
        field = fields.Decimal(places=2)
        values = []
        for i in range(rng.randint(15, 20)):
            r = rng.random()
            if r < 0.3:
                values.append(r < 0.15)
            elif r < 0.6:
                values.append(rng.randint(-99, 99))
            else:
                values.append(round(rng.uniform(-50, 50), 4))
        ok, bad = _run(field, values)
        self.assertEqual(len(ok) + len(bad), len(values))

    def test_04_junk_strings(self):
        rng = random.Random(404)
        field = fields.Decimal(places=1, rounding=decimal.ROUND_HALF_UP)
        values = [rng.choice(JUNK + _num_strings(rng, 3)) for _ in range(rng.randint(12, 18))]
        ok, bad = _run(field, values)
        self.assertGreater(len(bad), 0)

    def test_05_quantize_overflow(self):
        rng = random.Random(505)
        field = fields.Decimal(places=rng.randint(20, 26))
        values = []
        for _ in range(rng.randint(10, 14)):
            digits = rng.randint(1, 12)
            values.append(str(rng.randint(10 ** (digits - 1), 10**digits - 1)) + ".5")
        ok, bad = _run(field, values)
        self.assertEqual(len(ok) + len(bad), len(values))

    def test_06_deserialize_path(self):
        rng = random.Random(606)
        field = fields.Decimal(places=3, allow_nan=rng.random() < 0.5)
        values = _num_strings(rng, rng.randint(6, 10)) + [rng.choice(SPECIALS) for _ in range(4)]
        rng.shuffle(values)
        good = 0
        for v in values:
            try:
                field.deserialize(v)
                good += 1
            except ValidationError:
                pass
        direct_ok, _ = _run(field, values[::2])
        self.assertGreaterEqual(good, len(direct_ok))

    def test_07_serialize_then_validate(self):
        rng = random.Random(707)
        as_str = fields.Decimal(places=2, as_string=True)
        plain = fields.Decimal()
        raw = [rng.uniform(-1000, 1000) for _ in range(rng.randint(7, 11))]
        dumped = []
        for i, x in enumerate(raw):
            f = as_str if i % 3 else plain
            dumped.append(f.serialize("v", {"v": x}))
        dumped.append(as_str.serialize("v", {"v": None}))
        ok, bad = _run(plain, [d for d in dumped if d is not None])
        self.assertEqual(len(ok), len(dumped) - 1)
        self.assertFalse(bad)

    def test_08_many_fields(self):
        rng = random.Random(808)
        built = [
            fields.Decimal(places=rng.choice([None, 0, 2, 4]), allow_nan=rng.random() < 0.4)
            for _ in range(rng.randint(5, 8))
        ]
        total = 0
        for f in built:
            vals = _num_strings(rng, rng.randint(1, 3), scale=5)
            if rng.random() < 0.5:
                vals.append(rng.choice(SPECIALS))
            ok, bad = _run(f, vals)
            total += len(ok) + len(bad)
        self.assertGreater(total, len(built))

    def test_09_containers_and_none(self):
        rng = random.Random(909)
        field = fields.Decimal()
        pool = [None, [1, 2], {"a": 1}, (3,), b"7", 0, -0.0, 10**30]
        values = [rng.choice(pool) for _ in range(rng.randint(11, 16))]
        ok, bad = _run(field, values)
        self.assertEqual(len(ok) + len(bad), len(values))

    def test_10_integer_and_float_neighbours(self):
        rng = random.Random(1010)
        ints = fields.Integer(strict=False)
        floats = fields.Float(allow_nan=False)
        dec = fields.Decimal(places=2)
        values = [str(rng.randint(-9, 9)) if rng.random() < 0.7 else "x" for _ in range(rng.randint(6, 9))]
        _run(ints, values)
        _run(floats, values[: rng.randint(2, 5)])
        ok, _ = _run(dec, values)
        self.assertTrue(ok)

    def test_11_threshold_loop(self):
        rng = random.Random(1111)
        field = fields.Decimal(places=2)
        acc = decimal.Decimal(0)
        steps = 0
        while acc < 60 and steps < 40:
            step = rng.choice(["7.25", "3.333", "nan", "-1.5", True, "12.04"])
            try:
                acc += field._validated(step)
            except ValidationError:
                acc += 1
            steps += 1
        self.assertGreaterEqual(acc, 60)

    def test_12_scientific_notation(self):
        rng = random.Random(1212)
        field = fields.Decimal(places=rng.randint(2, 4), allow_nan=True)
        values = [f"{rng.randint(1, 9)}E{rng.randint(-8, 30)}" for _ in range(rng.randint(10, 15))]
        values += ["NaN", "-sNaN"][: rng.randint(1, 2)]
        ok, bad = _run(field, values)
        self.assertEqual(len(ok) + len(bad), len(values))
