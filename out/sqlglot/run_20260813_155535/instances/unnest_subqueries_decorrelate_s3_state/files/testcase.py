import unittest

from sqlglot import exp
from sqlglot.optimizer import optimize


class CorrelatedProjectionStateTest(unittest.TestCase):
    def test_generated_correlated_projection(self):
        width = sum((index % 4) + 1 for index in range(7))
        terms = []
        for index in range(width):
            outer_index = (index * 7 + width // 6) % width
            operator = ">" if (index * index + 3 * index + 7) % 5 == 0 else "="
            terms.append(f"i.k{index} {operator} o.c{outer_index}")

        sql = (
            "SELECT (SELECT SUM(i.payload) FROM inner_table AS i WHERE "
            + " AND ".join(terms)
            + ") AS score FROM outer_table AS o"
        )
        schema = {
            "outer_table": {f"c{index}": "INT" for index in range(width)},
            "inner_table": {
                **{f"k{index}": "INT" for index in range(width)},
                "payload": "INT",
            },
        }

        optimized = optimize(sql, schema=schema)

        self.assertIsInstance(optimized.find(exp.Join), exp.Join)
