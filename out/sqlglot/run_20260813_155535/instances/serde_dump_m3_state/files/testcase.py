import json
import random
import unittest

from sqlglot import exp
from sqlglot.serde import dump


class ExternalNode(exp.Expression):
    arg_types = {"this": False, "expressions": False}


class TestSerdeDumpProgramState(unittest.TestCase):
    def assert_valid_dump(self, payloads):
        self.assertIsInstance(payloads, list)
        self.assertGreater(len(payloads), 15)
        self.assertIn("c", payloads[0])
        self.assertIsInstance(json.dumps(payloads), str)

    def test_01_integer_sequence(self):
        rng = random.Random(1103)
        size = 19 + sum(rng.randrange(3) for _ in range(4))
        values = [(index * index + rng.randrange(97)) % 251 for index in range(size)]
        expression = exp.Tuple(expressions=values)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_02_generated_strings(self):
        rng = random.Random(2207)
        size = 20 + sum(rng.randrange(2) for _ in range(7))
        values = [
            f"item_{(index * 17 + rng.randrange(101)) % 307:03d}"
            for index in range(size)
        ]
        expression = exp.Array(expressions=values)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_03_mixed_primitive_branches(self):
        rng = random.Random(3301)
        size = 21 + sum(rng.randrange(3) for _ in range(5))
        values = [
            (
                None
                if index % 7 == 0
                else index % 2 == 0
                if index % 5 == 0
                else (index * rng.randrange(3, 29)) % 173
                if index % 3
                else f"mixed_{rng.randrange(1000)}"
            )
            for index in range(size)
        ]
        expression = exp.Anonymous(this="generated_mix", expressions=values)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_04_nested_expression_layers(self):
        rng = random.Random(4409)
        width = 5 + sum(rng.randrange(2) for _ in range(4))
        children = [
            exp.Array(
                expressions=[
                    (outer * 31 + inner * 13 + rng.randrange(19)) % 199
                    for inner in range(3 + outer % 3)
                ]
            )
            for outer in range(width)
        ]
        expression = exp.Tuple(expressions=children)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_05_comments_and_metadata(self):
        rng = random.Random(5501)
        size = 17 + sum(rng.randrange(3) for _ in range(5))
        children = [
            exp.Literal.number((index * 37 + rng.randrange(41)) % 223)
            for index in range(size)
        ]
        for index, child in enumerate(children):
            if index % 2:
                child.add_comments([f"note-{(index * 11 + size) % 79}"])
            if index % 3 == 1:
                child.meta["rank"] = (index * index + size) % 67
                child.meta["enabled"] = index % 4 == 1
        expression = exp.Tuple(expressions=children)
        expression.meta["seed_checksum"] = sum(child.to_py() for child in children) % 997
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_06_recursive_type_dump(self):
        rng = random.Random(6607)
        size = 18 + sum(rng.randrange(2) for _ in range(6))
        values = [(index * rng.randrange(5, 37) + size) % 181 for index in range(size)]
        expression = exp.Array(expressions=values)
        expression._type = exp.DataType.build("ARRAY<DECIMAL(12, 3)>")
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_07_dtype_enum_values(self):
        rng = random.Random(7703)
        candidates = list(exp.DType)
        size = 19 + sum(rng.randrange(3) for _ in range(4))
        values = [
            candidates[(index * 23 + rng.randrange(len(candidates))) % len(candidates)]
            for index in range(size)
        ]
        expression = exp.Tuple(expressions=values)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_08_scalar_and_array_arguments(self):
        rng = random.Random(8807)
        size = 16 + sum(rng.randrange(4) for _ in range(5))
        expression = exp.Tuple(
            this=f"root_{rng.randrange(100, 999)}",
            expression=(size * rng.randrange(7, 31)) % 257,
            distinct=size % 2 == 0,
            expressions=[
                f"leaf_{(index * 29 + rng.randrange(83)) % 401}"
                for index in range(size)
            ],
        )
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_09_mapping_and_tuple_values(self):
        rng = random.Random(9901)
        size = 18 + sum(rng.randrange(3) for _ in range(5))
        values = [
            {
                "slot": index,
                "weight": (index * 43 + rng.randrange(59)) % 211,
                "flags": (index % 2 == 0, index % 5 == 0),
            }
            for index in range(size)
        ]
        expression = exp.Array(expressions=values)
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_10_irregular_nested_widths(self):
        rng = random.Random(10103)
        groups = 6 + sum(rng.randrange(2) for _ in range(5))
        expression = exp.Array(
            expressions=[
                exp.Tuple(
                    expressions=[
                        f"g{group}_{(item * 47 + rng.randrange(71)) % 313}"
                        for item in range(2 + group % 5)
                    ]
                )
                for group in range(groups)
            ]
        )
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_11_external_expression_class(self):
        rng = random.Random(11113)
        size = 20 + sum(rng.randrange(3) for _ in range(5))
        expression = ExternalNode(
            this=(size * rng.randrange(11, 41)) % 269,
            expressions=[
                (index * index * 7 + rng.randrange(101)) % 283
                for index in range(size)
            ],
        )
        expression.add_comments([f"external-{sum(expression.expressions) % 109}"])
        payloads = dump(expression)
        self.assert_valid_dump(payloads)

    def test_12_deep_single_child_chain(self):
        rng = random.Random(12109)
        depth = 17 + sum(rng.randrange(3) for _ in range(6))
        expression = exp.Literal.number(rng.randrange(13, 97))
        for level in range(depth):
            expression = (
                exp.Paren(this=expression)
                if level % 3
                else exp.Neg(this=expression)
            )
            if level % 4 == 2:
                expression.meta["depth_code"] = (level * 19 + depth) % 127
        payloads = dump(expression)
        self.assert_valid_dump(payloads)
