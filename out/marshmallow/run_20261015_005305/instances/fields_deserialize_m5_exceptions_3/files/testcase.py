import datetime as dt
import random
import unittest
from decimal import Decimal

from marshmallow import fields


def _run(field, values):
    """Feed every value to TimeDelta._deserialize; return (ok_results, failure_count)."""
    ok, failed = [], 0
    for value in values:
        try:
            ok.append(field._deserialize(value, "span", {}))
        except Exception:  # noqa: BLE001 - outcomes are recorded generically
            failed += 1
    return ok, failed


class Ratio:
    """Object whose float conversion divides two derived numbers."""

    def __init__(self, num, den):
        self.num = num
        self.den = den

    def __float__(self):
        return self.num / self.den


class LookupFloat:
    """Float conversion backed by a table; misses are handled internally."""

    table = {"a": 1.5, "b": 2.25, "c": 40.0}

    def __init__(self, key):
        self.key = key

    def __float__(self):
        try:
            return self.table[self.key]
        except KeyError:
            return float(len(self.key))


class BadFloat:
    """__float__ that returns something that is not a float."""

    def __init__(self, payload):
        self.payload = payload

    def __float__(self):
        return self.payload


class TestTimeDeltaDeserializeExceptions(unittest.TestCase):
    def test_numeric_strings_mixed(self):
        rng = random.Random(1572)
        tokens = []
        for i in range(30):
            pick = rng.randint(0, 5)
            if pick <= 2:
                tokens.append(f"{rng.uniform(-500, 500):.3f}")
            elif pick == 3:
                tokens.append(f"{rng.randint(1, 99)}{rng.choice('xyz')}")
            elif pick == 4:
                tokens.append(rng.choice(["inf", "-inf", "1e400", "nan", "NaN"]))
            else:
                tokens.append(" " + str(rng.randint(0, 9) * i) + " ")
        ok, failed = _run(fields.TimeDelta(), tokens)
        self.assertEqual(len(ok) + failed, len(tokens))
        self.assertGreater(failed, 0)

    def test_none_and_containers(self):
        rng = random.Random(7)
        shapes = [None, [], {}, (), set()]
        values = [shapes[rng.randrange(len(shapes))] for _ in range(9)]
        values += [[rng.random()] for _ in range(3)]
        ok, failed = _run(fields.TimeDelta(precision="minutes"), values)
        self.assertEqual(ok, [])
        self.assertEqual(failed, len(values))

    def test_weeks_magnitude_sweep(self):
        values = [sign * 10**k for k in range(4, 11) for sign in (1, -1)]
        ok, failed = _run(fields.TimeDelta(precision="WEEKS"), values)
        self.assertEqual(len(ok) + failed, len(values))
        self.assertTrue(all(isinstance(v, dt.timedelta) for v in ok))

    def test_huge_integers(self):
        field = fields.TimeDelta(precision="microseconds")
        values = [3**k for k in range(640, 660, 2)]
        crashed = 0
        for value in values:
            with self.assertRaises(Exception) as ctx:
                field._deserialize(value, "span", {})
            if ctx.exception.__cause__ is None:
                crashed += 1
        self.assertGreater(crashed, 0)

    def test_ratio_objects(self):
        rng = random.Random(99)
        values = [Ratio(rng.randint(1, 50), rng.randint(0, 4)) for _ in range(14)]
        ok, failed = _run(fields.TimeDelta(precision="hours"), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_lookup_objects_swallow_misses(self):
        keys = ["a", "zz", "b", "qqq", "c", "wxyz", "a", "b"]
        ok, failed = _run(fields.TimeDelta(precision="days"), [LookupFloat(k) for k in keys])
        self.assertEqual(failed, 0)
        self.assertEqual(len(ok), len(keys))

    def test_timedelta_passthrough(self):
        base = [dt.timedelta(seconds=s * 37) for s in range(12)]
        ok, failed = _run(fields.TimeDelta(precision="milliseconds"), base)
        self.assertEqual(failed, 0)
        self.assertEqual(ok, base)

    def test_decimal_inputs(self):
        specs = ["1.25", "sNaN", "NaN", "Infinity", "-0.5", "-sNaN", "1E+12", "7"]
        values = [Decimal(s) for s in specs for _ in range(1 + len(s) % 2)]
        ok, failed = _run(fields.TimeDelta(precision="days"), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_mutated_precision(self):
        field = fields.TimeDelta()
        field.precision = "fortnights"
        values = ["3", "x3", 4.5, None, "8"]
        crashed = 0
        for value in values:
            with self.assertRaises(Exception):
                field._deserialize(value, "span", {})
            crashed += 1
        self.assertEqual(crashed, len(values))

    def test_bytes_inputs(self):
        rng = random.Random(4)
        values = []
        for _ in range(10):
            n = rng.randint(0, 9)
            values.append(str(n).encode() if n % 3 else f"{n}q".encode())
        values.append(bytearray(b"12.5"))
        values.append(memoryview(b"6"))
        ok, failed = _run(fields.TimeDelta(precision="seconds"), values)
        self.assertEqual(len(ok) + failed, len(values))

    def test_bad_float_payloads(self):
        payloads = [1.0, "2.0", 3, None, 4.5, b"5", 6.25]
        ok, failed = _run(fields.TimeDelta(), [BadFloat(p) for p in payloads])
        self.assertEqual(len(ok) + failed, len(payloads))

    def test_day_bounds_and_bools(self):
        values = [True, False]
        values += [(-1) ** k * (999_999_990 + 3 * k) for k in range(8)]
        values += [k * 1.0e5 for k in range(2)]
        ok, failed = _run(fields.TimeDelta(precision="days"), values)
        self.assertEqual(len(ok) + failed, len(values))
