import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.annotate_types import annotate_types


class TestAnnotateByArgsDataFlow(unittest.TestCase):
    def _check(self, sql, *, dialect=None, schema=None):
        tree = parse_one(sql, dialect=dialect)
        annotated = annotate_types(tree, dialect=dialect, schema=schema)
        self.assertIs(annotated, tree)
        self.assertIsInstance(annotated, exp.Expression)
        self.assertTrue(all(node.type is not None for node in annotated.walk()))

    def test_integer_array_accumulation(self):
        rng = random.Random(0xA401)
        values = [rng.randrange(1, 900) + index * index for index in range(19)]
        self._check(f"SELECT ARRAY({', '.join(map(str, values))}) AS payload")

    def test_mixed_numeric_literal_array(self):
        rng = random.Random(0xA402)
        values = []
        for index in range(21):
            value = rng.randrange(2, 700) + index
            values.append(str(value) if index % 3 else f"{value / 7:.3f}")
        self._check(f"SELECT ARRAY({', '.join(values)}) AS measurements")

    def test_alternating_columns_and_literals(self):
        rng = random.Random(0xA403)
        items = []
        for index in range(23):
            if index % 4 in (0, 3):
                items.append(f"t.metric_{index % 7}")
            else:
                items.append(str(rng.randrange(5, 500) + index))
        columns = {f"metric_{index}": "SMALLINT" for index in range(7)}
        self._check(
            f"SELECT ARRAY({', '.join(items)}) FROM telemetry AS t",
            schema={"telemetry": columns},
        )

    def test_bigquery_nonliteral_priority(self):
        rng = random.Random(0xA404)
        items = []
        for index in range(17):
            if index % 5 == 2:
                items.append(f"b.value_{index % 4}")
            else:
                items.append(str(rng.randrange(10, 600) * (index + 1)))
        columns = {f"value_{index}": "INT64" for index in range(4)}
        self._check(
            f"SELECT [{', '.join(items)}] FROM batch AS b",
            dialect="bigquery",
            schema={"batch": columns},
        )

    def test_nested_arrays_stop_outer_coercion(self):
        rng = random.Random(0xA405)
        groups = []
        for outer in range(8):
            values = [rng.randrange(1, 300) + outer * inner for inner in range(6)]
            groups.append(f"ARRAY({', '.join(map(str, values))})")
        self._check(f"SELECT ARRAY({', '.join(groups)}) AS matrix")

    def test_many_case_result_arguments(self):
        rng = random.Random(0xA406)
        branches = []
        for index in range(18):
            threshold = rng.randrange(20, 800)
            result = threshold / 9 if index % 4 == 0 else threshold + index
            branches.append(f"WHEN {index} < {threshold} THEN {result}")
        self._check(f"SELECT CASE {' '.join(branches)} ELSE 0 END AS chosen")

    def test_coalesce_column_literal_interleave(self):
        rng = random.Random(0xA407)
        arguments = []
        for index in range(20):
            if index % 3 == 1:
                arguments.append(f"c.option_{index % 6}")
            else:
                arguments.append(str(rng.randrange(1, 450) + index * 2))
        columns = {f"option_{index}": "BIGINT" for index in range(6)}
        self._check(
            f"SELECT COALESCE({', '.join(arguments)}) FROM choices AS c",
            schema={"choices": columns},
        )

    def test_greatest_real_type_progression(self):
        rng = random.Random(0xA408)
        arguments = [
            f"{(rng.randrange(10, 900) + index) / (index % 7 + 2):.4f}"
            if index % 2
            else str(rng.randrange(10, 900))
            for index in range(22)
        ]
        self._check(f"SELECT GREATEST({', '.join(arguments)}) AS peak")

    def test_generate_series_argument_groups(self):
        rng = random.Random(0xA409)
        projections = []
        for index in range(9):
            start = rng.randrange(1, 40)
            stop = start + rng.randrange(12, 80)
            step = index % 5 + 1
            projections.append(f"GENERATE_SERIES({start}, {stop}, {step}) AS series_{index}")
        self._check(f"SELECT {', '.join(projections)}")

    def test_promoted_sum_variants(self):
        rng = random.Random(0xA40A)
        projections = []
        for index in range(16):
            base = rng.randrange(2, 200)
            operand = f"{base}.25" if index % 3 == 0 else str(base)
            projections.append(f"SUM({operand}) AS total_{index}")
        self._check(f"SELECT {', '.join(projections)}")

    def test_unknown_columns_short_circuit(self):
        rng = random.Random(0xA40B)
        projections = []
        for index in range(15):
            known = rng.randrange(3, 500)
            arguments = [str(known + offset) for offset in range(index % 4 + 1)]
            arguments.insert(index % len(arguments), f"u.missing_{index}")
            projections.append(f"ARRAY({', '.join(arguments)}) AS uncertain_{index}")
        self._check(f"SELECT {', '.join(projections)} FROM unresolved AS u")

    def test_snowflake_concat_ws_batches(self):
        rng = random.Random(0xA40C)
        projections = []
        for group in range(7):
            arguments = []
            for index in range(9):
                width = rng.randrange(1, 6)
                arguments.append("'" + chr(97 + (group + index) % 26) * width + "'")
            projections.append(f"CONCAT_WS('|', {', '.join(arguments)}) AS joined_{group}")
        self._check(f"SELECT {', '.join(projections)}", dialect="snowflake")
