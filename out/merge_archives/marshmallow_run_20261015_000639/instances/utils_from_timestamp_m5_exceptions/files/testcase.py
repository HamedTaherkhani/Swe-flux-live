import datetime as dt
import random
import unittest
from decimal import Decimal
from fractions import Fraction

from marshmallow.utils import from_timestamp


def _drive(values):
    """Call from_timestamp on every value, recording outcomes generically."""
    ok, failed = [], []
    for value in values:
        try:
            ok.append(from_timestamp(value))
        except Exception as exc:  # noqa: BLE001 - outcomes are recorded, not named
            failed.append(exc)
    return ok, failed


class Ratio:
    """Float protocol computed from a numerator and a denominator."""

    def __init__(self, num, den):
        self.num = num
        self.den = den

    def __float__(self):
        return self.num / self.den


class LookupStamp:
    """Float protocol that resolves a key through a table, with a fallback."""

    TABLE = {"alpha": 1000.0, "beta": 2500.5, "gamma": -40.0}

    def __init__(self, key, fallback):
        self.key = key
        self.fallback = fallback

    def __float__(self):
        try:
            return self.TABLE[self.key]
        except KeyError:
            return self.fallback


class Probe:
    """Float protocol that reads an attribute chosen at construction time."""

    def __init__(self, attr):
        self.attr = attr
        self.seconds = 86400 * 3

    def __float__(self):
        return float(getattr(self, self.attr))


class TestFromTimestampExceptions(unittest.TestCase):
    def test_signed_numeric_mix(self):
        rng = random.Random(11)
        values = []
        for i in range(24):
            base = rng.randint(0, 2_000_000_000)
            sign = -1 if rng.random() < 0.3 else 1
            values.append(sign * base if i % 2 else float(sign * base) / 7)
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
        self.assertTrue(all(isinstance(d, dt.datetime) for d in ok))
        self.assertTrue(ok)

    def test_boolean_interleave(self):
        rng = random.Random(23)
        values = []
        for i in range(20):
            r = rng.random()
            if r < 0.35:
                values.append(bool(i % 3))
            else:
                values.append(int(r * 1000) - 200)
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
        self.assertTrue(all(d.tzinfo is None for d in ok))

    def test_string_forms(self):
        rng = random.Random(5)
        templates = ["{n}", " {n} ", "-{n}", "{n}.5e3", "0x{n}", "{n}e400", "n{n}"]
        values = [rng.choice(templates).format(n=rng.randint(1, 999)) for _ in range(22)]
        values += ["nan", "-inf", "inf"]
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
        self.assertGreater(len(failed), 0)

    def test_integer_magnitude_ladder(self):
        values = [10**k + k for k in range(4, 26, 1)]
        values.append(10 ** (300 + len(values) * 4))
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
        self.assertTrue(all(isinstance(e, Exception) for e in failed))

    def test_float_power_sweep(self):
        values = [float(2**k) * (1.5 if k % 4 == 0 else 1.0) for k in range(30, 72, 3)]
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
        self.assertGreater(len(failed), len(ok))

    def test_non_numeric_objects(self):
        factories = [lambda i: None, lambda i: [i], lambda i: {"v": i},
                     lambda i: complex(i, 1), lambda i: str(i * 37), lambda i: (i,)]
        values = [factories[(i * 5) % len(factories)](i) for i in range(15)]
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_fraction_inputs(self):
        rng = random.Random(99)
        values = []
        for _ in range(16):
            num = rng.randint(-5000, 90000)
            den = rng.randint(1, 13)
            if rng.random() < 0.25:
                num *= 10 ** rng.choice([200, 330, 400])
            values.append(Fraction(num, den))
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_decimal_inputs(self):
        rng = random.Random(3)
        specials = ["NaN", "sNaN", "-0", "Infinity", "-Infinity", "1E+20", "2.5E+11"]
        values = []
        for i in range(18):
            if i % 3 == 0:
                values.append(Decimal(specials[(i // 3 + rng.randint(0, 6)) % len(specials)]))
            else:
                values.append(Decimal(rng.randint(-300, 3000)) / Decimal(4))
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_ratio_protocol(self):
        rng = random.Random(41)
        values = []
        for _ in range(18):
            num = rng.randint(-50, 5000)
            den = rng.randint(0, 6) - 1
            values.append(Ratio(num, den))
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_lookup_fallbacks(self):
        rng = random.Random(8)
        keys = ["alpha", "beta", "gamma", "delta", "omega"]
        values = [LookupStamp(rng.choice(keys), rng.choice([0.0, 12.25, -3.0, 7e11]))
                  for _ in range(16)]
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_attribute_probes(self):
        rng = random.Random(17)
        attrs = ["seconds", "attr", "minutes", "seconds"]
        values = [Probe(rng.choice(attrs)) for _ in range(14)]
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))

    def test_all_valid_timestamps(self):
        rng = random.Random(2024)
        values = [rng.uniform(0, 4_000_000_000) for _ in range(12)]
        values += [str(rng.randint(0, 10**9)) for _ in range(6)]
        values += [Fraction(rng.randint(0, 10**6), rng.randint(1, 9)) for _ in range(4)]
        ok, failed = _drive(values)
        self.assertEqual(len(failed), 0)
        self.assertEqual(len(ok), len(values))

    def test_bytes_inputs(self):
        rng = random.Random(64)
        values = []
        for i in range(14):
            digits = str(rng.randint(0, 10**8)).encode()
            if i % 4 == 1:
                digits = b"-" + digits
            elif i % 5 == 2:
                digits = digits + b"z"
            values.append(bytearray(digits) if i % 2 else digits)
        ok, failed = _drive(values)
        self.assertEqual(len(ok) + len(failed), len(values))
