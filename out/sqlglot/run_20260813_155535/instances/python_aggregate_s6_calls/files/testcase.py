import random
import unittest

from sqlglot import planner
from sqlglot.executor.python import PythonExecutor
from sqlglot.executor.table import Table
from sqlglot.optimizer import optimize


class TestPythonAggregateCalls(unittest.TestCase):
    def test_seeded_grouped_aggregation(self):
        rng = random.Random(0xA66E)
        rows = []
        rolling = rng.randrange(17, 43)

        for index in range(127):
            rolling = (rolling * 37 + rng.randrange(3, 997) + index) % 1009
            category = (rolling + index * 11) % 19
            value = rng.randrange(-35, 91) + rolling % 13
            weight = 1 + (rng.randrange(0, 71) + rolling) % 17
            rows.append((category, value, weight))

        metrics = [
            ("SUM(value)", "total"),
            ("COUNT(*)", "row_count"),
            ("MAX(weight)", "max_weight"),
            ("MIN(weight)", "min_weight"),
            ("AVG(value)", "mean_value"),
            ("SUM(weight)", "weight_total"),
            ("MAX(value)", "max_value"),
            ("MIN(value)", "min_value"),
        ]
        projections = ", ".join(f"{expression} AS {alias}" for expression, alias in metrics)
        query = (
            f"SELECT category, {projections} FROM source "
            "GROUP BY category HAVING SUM(value) > 0"
        )
        schema = {"source": {"category": "INT", "value": "INT", "weight": "INT"}}
        step = planner.Plan(
            optimize(query, schema=schema, leave_tables_isolated=True)
        ).root

        self.assertIsInstance(step, planner.Aggregate)
        executor = PythonExecutor()
        context = executor.context(
            {"source": Table(("category", "value", "weight"), rows)}
        )
        result = executor.aggregate(step, context).tables["source"]

        self.assertEqual(len(result.columns), len(metrics) + 1)
        self.assertGreater(len(result.rows), len(metrics))
        self.assertTrue(all(len(row) == len(result.columns) for row in result.rows))
