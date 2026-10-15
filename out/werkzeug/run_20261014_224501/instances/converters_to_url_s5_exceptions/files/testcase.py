import random
import unittest
from decimal import Decimal
from fractions import Fraction

from werkzeug.routing import Map
from werkzeug.routing.converters import FloatConverter


def _build_values(seed):
    rng = random.Random(seed)
    seps = [".", "_", ". ", "..", "e", "E-"]
    values = []
    for i in range(60):
        kind = rng.randrange(6)
        mant = rng.randint(1, 9999)
        exp = rng.randint(-30, 30)
        if kind == 0:
            values.append(mant * 10.0**exp)
        elif kind == 1:
            values.append(Fraction(mant, rng.randint(1, 97)) * 10**exp)
        elif kind == 2:
            values.append(Decimal(mant).scaleb(exp))
        elif kind == 3:
            sep = seps[rng.randrange(len(seps))]
            values.append(f" {mant // 100}{sep}{mant % 100:02d} ")
        elif kind == 4:
            values.append(mant * 10**exp if exp >= 0 else mant)
        else:
            values.append(-(mant * 10.0**exp) * (i % 7 == 0) + 0.0)
    return values


class FloatToUrlTest(unittest.TestCase):
    def test_float_to_url_stream(self):
        conv = FloatConverter(Map(), max=1e31)
        values = _build_values(31)
        produced = []
        failure = None
        for value in values:
            try:
                produced.append(conv.to_url(value))
            except Exception as exc:  # stop at the first failing value
                failure = exc
                break
        self.assertIsNotNone(failure)
        self.assertGreaterEqual(len(produced), 15)
        self.assertTrue(all("e" not in s for s in produced))
