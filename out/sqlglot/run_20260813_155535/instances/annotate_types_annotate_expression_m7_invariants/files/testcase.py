import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.annotate_types import annotate_types


class TestAnnotateExpressionInvariants(unittest.TestCase):
    def _check(self, sql, *, dialect=None, schema=None):
        tree = parse_one(sql, dialect=dialect)
        annotated = annotate_types(tree, dialect=dialect, schema=schema)
        self.assertIs(annotated, tree)
        self.assertIsInstance(annotated, exp.Expression)
        self.assertTrue(all(node.type is not None for node in annotated.walk()))

    def test_generated_arithmetic_projections(self):
        rng = random.Random(0xA110)
        terms = []
        for index in range(7):
            left = rng.randrange(2, 41)
            right = rng.randrange(3, 53)
            operator = ("+", "-", "*", "/")[index % 4]
            terms.append(f"(({index} + {left}) {operator} ({right} - {index % 7})) AS a_{index}")
        self._check(f"SELECT {', '.join(terms)}")

    def test_generated_case_expressions(self):
        branches = []
        for index in range(6):
            modulus = 2 + index % 6
            branches.append(
                f"CASE WHEN {index} % {modulus} = 0 THEN {index} * 1.5 "
                f"WHEN {index} > {modulus} THEN {index} ELSE NULL END AS c_{index}"
            )
        self._check(f"SELECT {', '.join(branches)}")

    def test_generated_string_functions(self):
        rng = random.Random(0x51A1)
        projections = []
        for index in range(7):
            width = rng.randrange(1, 8)
            token = chr(97 + index % 26) * width
            projections.append(
                f"CONCAT(UPPER('{token}'), LOWER(CAST({index * width} AS TEXT))) AS s_{index}"
            )
        self._check(f"SELECT {', '.join(projections)}")

    def test_qualified_schema_columns(self):
        columns = {f"metric_{index}": ("DOUBLE" if index % 4 == 0 else "INT") for index in range(8)}
        projections = [
            f"t.metric_{index} + {index % 9} AS adjusted_{index}" for index in range(8)
        ]
        self._check(
            f"SELECT {', '.join(projections)} FROM measurements AS t",
            schema={"measurements": columns},
        )

    def test_generated_arrays_and_indexes(self):
        projections = []
        for index in range(6):
            values = ", ".join(str(index + offset * offset) for offset in range(5))
            projections.append(f"ARRAY({values})[{1 + index % 4}] AS item_{index}")
        self._check(f"SELECT {', '.join(projections)}")

    def test_generated_maps(self):
        projections = []
        for index in range(6):
            keys = ", ".join(f"'{index}_{offset}'" for offset in range(4))
            values = ", ".join(str((index + 1) * (offset + 2)) for offset in range(4))
            projections.append(
                f"MAP_FROM_ARRAYS(ARRAY({keys}), ARRAY({values}))['{index}_{index % 4}'] AS m_{index}"
            )
        self._check(f"SELECT {', '.join(projections)}", dialect="spark")

    def test_generated_window_functions(self):
        projections = ["department"]
        for index in range(5):
            frame = index % 5
            projections.append(
                "SUM(score + {offset}) OVER (PARTITION BY department ORDER BY event_id "
                "ROWS BETWEEN {frame} PRECEDING AND CURRENT ROW) AS w_{index}".format(
                    offset=index % 7, frame=frame, index=index
                )
            )
        self._check(
            f"SELECT {', '.join(projections)} FROM events",
            schema={"events": {"department": "TEXT", "score": "DOUBLE", "event_id": "INT"}},
        )

    def test_generated_union_chain(self):
        selects = [
            f"SELECT {index} AS key_value, {index * index + index % 3} AS payload"
            for index in range(6)
        ]
        self._check(" UNION ALL ".join(selects))

    def test_generated_cte_join(self):
        left_values = ", ".join(
            f"({index}, {index * 3 + 1})" for index in range(1, 7)
        )
        right_values = ", ".join(
            f"({index}, {index * index - 2})" for index in range(1, 7)
        )
        sql = (
            f"WITH lhs(k, v) AS (VALUES {left_values}), rhs(k, w) AS (VALUES {right_values}) "
            "SELECT lhs.k, lhs.v + rhs.w AS combined FROM lhs JOIN rhs ON lhs.k = rhs.k"
        )
        self._check(sql)

    def test_generated_boolean_predicates(self):
        rng = random.Random(0xB001)
        predicates = []
        for index in range(7):
            lower = rng.randrange(0, 200)
            upper = lower + rng.randrange(5, 35)
            predicates.append(
                f"(({index * 7} BETWEEN {lower} AND {upper}) OR "
                f"({index} IN ({index % 3}, {index % 5}, {index % 11})))"
            )
        self._check(f"SELECT {' AND '.join(predicates)} AS decision")

    def test_single_unnest_source_column(self):
        values = ", ".join(str((index + 2) * (index % 5 + 1)) for index in range(7))
        alias = "".join(chr(code) for code in (113,))
        self._check(f"SELECT {alias}.value FROM UNNEST(ARRAY({values})) AS {alias}(value)")

    def test_generated_order_aliases(self):
        rng = random.Random(0x0ADE)
        projections = []
        aliases = []
        for index in range(7):
            alias = f"ranked_{index}"
            aliases.append(alias)
            projections.append(
                f"(base_value * {rng.randrange(2, 17)} + {rng.randrange(1, 91)}) AS {alias}"
            )
        order = ", ".join(
            f"{alias} {'DESC' if index % 3 == 0 else 'ASC'}"
            for index, alias in enumerate(reversed(aliases))
        )
        self._check(
            f"SELECT {', '.join(projections)} FROM ranking_input ORDER BY {order}",
            schema={"ranking_input": {"base_value": "INT"}},
        )
