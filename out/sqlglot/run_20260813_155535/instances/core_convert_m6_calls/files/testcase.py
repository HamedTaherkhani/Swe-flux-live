import datetime
import random
import unittest
from collections import namedtuple
from decimal import Decimal
from fractions import Fraction

from sqlglot import exp


Point = namedtuple("Point", "left right")


class Payload:
    def __init__(self, seed):
        self.label = f"payload_{seed % 7}"
        self.amount = seed * seed - seed


class Opaque:
    __slots__ = ()


class TestConvertCallGraph(unittest.TestCase):
    def make_column(self, seed):
        return exp.column(
            f"metric_{seed % 7}",
            table=f"source_{seed % 5}",
            fields=[f"part_{seed % 3}", f"leaf_{seed % 4}"] if seed % 2 else None,
        )

    def test_seeded_scalar_operators(self):
        rng = random.Random(7)
        values = []
        for index in range(3 * 7):
            branch = rng.randrange(5)
            values.append(
                (
                    f"text_{rng.randrange(4 * 5)}",
                    rng.randrange(-3 * 7, 4 * 7),
                    bool(rng.randrange(2)),
                    None,
                    rng.random() * (index + 1),
                )[branch]
            )

        expressions = [self.make_column(i) + value for i, value in enumerate(values)]
        self.assertTrue(all(isinstance(expression, exp.Add) for expression in expressions))

    def test_numeric_families_between(self):
        rng = random.Random(3 * 5)
        expressions = []
        for index in range(3 * 5):
            low = Decimal(rng.randrange(-4 * 5, 0)) / Decimal(index % 3 + 1)
            high = Fraction(rng.randrange(1, 5 * 5), index % 4 + 1)
            expressions.append(self.make_column(index).between(low, high, symmetric=index % 2 == 0))

        self.assertTrue(all(isinstance(expression, exp.Between) for expression in expressions))

    def test_variadic_membership(self):
        rng = random.Random(4 * 5)
        values = [
            rng.choice((index, f"group_{index % 6}", index % 3 == 0, float("nan"), None))
            for index in range(4 * 5)
        ]
        expression = self.make_column(rng.randrange(3 * 7)).isin(*values, copy=False)

        self.assertIsInstance(expression, exp.In)
        self.assertEqual(len(expression.expressions), len(values))

    def test_binary_payloads(self):
        rng = random.Random(3 * 6)
        payloads = [
            bytes(rng.randrange(2**8) for _ in range(index % 5 + 1))
            for index in range(3 * 6)
        ]
        expressions = [self.make_column(i) - payload for i, payload in enumerate(payloads)]

        self.assertTrue(all(isinstance(expression, exp.Sub) for expression in expressions))

    def test_temporal_boundaries(self):
        rng = random.Random(4 * 4)
        expressions = []
        for index in range(4 * 4):
            day = datetime.date(2**11 + index % 3, index % 9 + 1, index % 2 + 1)
            clock = datetime.time(index % 2**4, rng.randrange(6 * 10), rng.randrange(6 * 10))
            expressions.append(self.make_column(index).between(day, clock))

        self.assertTrue(all(isinstance(expression, exp.Between) for expression in expressions))

    def test_timezone_aware_datetimes(self):
        rng = random.Random(3 * 7)
        offsets = [
            datetime.timezone(datetime.timedelta(minutes=(rng.randrange(-3 * 4, 3 * 5) * 3 * 5)))
            for _ in range(3 * 5)
        ]
        expressions = [
            self.make_column(index).eq(
                datetime.datetime(
                    2**11 + index % 4,
                    index % 9 + 1,
                    index % 2 + 1,
                    rng.randrange(2**4),
                    rng.randrange(6 * 10),
                    tzinfo=zone,
                )
            )
            for index, zone in enumerate(offsets)
        ]

        self.assertTrue(all(isinstance(expression, exp.EQ) for expression in expressions))

    def test_nested_sequence_values(self):
        rng = random.Random(5 * 5)
        values = [
            [
                (index, f"v_{rng.randrange(3 * 7)}"),
                [rng.randrange(5 * 5), index % 2 == 0, None],
            ]
            for index in range(3 * 5)
        ]
        expressions = [self.make_column(i) * value for i, value in enumerate(values)]

        self.assertTrue(all(isinstance(expression, exp.Mul) for expression in expressions))

    def test_named_tuple_records(self):
        rng = random.Random(3 * 9)
        records = [
            Point(rng.randrange(-4 * 4, 4 * 4), f"point_{rng.randrange(5 * 5)}")
            for _ in range(3 * 5)
        ]
        expression = self.make_column(rng.randrange(4 * 5)).isin(*records)

        self.assertIsInstance(expression, exp.In)
        self.assertEqual(len(expression.expressions), len(records))

    def test_nested_mapping_values(self):
        rng = random.Random(4 * 7)
        mappings = [
            {
                f"k_{index % 5}": [rng.randrange(3 * 7), index % 2 == 0],
                index: {"inner": rng.randrange(4 * 6)},
            }
            for index in range(3 * 5)
        ]
        expressions = [self.make_column(i) / mapping for i, mapping in enumerate(mappings)]

        self.assertTrue(all(isinstance(expression, exp.Div) for expression in expressions))

    def test_object_attribute_records(self):
        rng = random.Random(5 * 7)
        records = [Payload(rng.randrange(5 * 5)) for _ in range(3 * 5)]
        expressions = [
            self.make_column(index).between(record, [record.label, record.amount])
            for index, record in enumerate(records)
        ]

        self.assertTrue(all(isinstance(expression, exp.Between) for expression in expressions))

    def test_expression_operands_and_unnest(self):
        rng = random.Random(6 * 7)
        operands = [exp.Literal.number(rng.randrange(4 * 7)) for _ in range(3 * 5)]
        comparisons = [self.make_column(i) >= operand for i, operand in enumerate(operands)]
        membership = self.make_column(rng.randrange(3 * 6)).isin(
            *operands[: rng.randrange(3, 8)],
            query=f"SELECT key FROM lookup_{rng.randrange(5)}",
            unnest=[f"ARRAY({i}, {i + 1})" for i in range(3 * 5)],
        )

        self.assertTrue(all(isinstance(expression, exp.GTE) for expression in comparisons))
        self.assertIsInstance(membership, exp.In)
        self.assertIsNotNone(membership.args.get("unnest"))

    def test_reverse_operations_and_rejections(self):
        rng = random.Random(7 * 7)
        reverse = [
            rng.randrange(-3 * 7, 3 * 7) - self.make_column(index)
            for index in range(3 * 5)
        ]
        failures = 0
        for index in range(3 * 5):
            with self.assertRaises(ValueError):
                self.make_column(index) + Opaque()
            failures += 1

        self.assertTrue(all(isinstance(expression, exp.Sub) for expression in reverse))
        self.assertEqual(failures, len(reverse))
