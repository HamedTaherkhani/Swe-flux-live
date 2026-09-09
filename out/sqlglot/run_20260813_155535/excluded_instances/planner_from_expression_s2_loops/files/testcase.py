import random
import unittest

from sqlglot import parse_one
from sqlglot.planner import Plan, Sort


class TestPlannerLoopBehavior(unittest.TestCase):
    def test_generated_aggregate_plan(self):
        rng = random.Random(0x5A17)
        projections = ["x.bucket AS grouping_key"]

        for index in range(27):
            expression = "x.bucket"
            for _ in range(2 + rng.randrange(5)):
                factor = rng.randrange(2, 19)
                offset = rng.randrange(1, 97)
                if rng.randrange(2):
                    expression = f"(({expression} * {factor}) + {offset})"
                else:
                    expression = f"(({expression} + {offset}) / {factor})"

            if index % 5 == 0:
                expression = f"SUM({expression} + x.measure_{index})"

            projections.append(f"{expression} AS feature_{index}")

        query = (
            f"SELECT {', '.join(projections)} "
            "FROM generated_table AS x "
            "GROUP BY x.bucket "
            "HAVING SUM(x.guard + 1) > 0 "
            "ORDER BY SUM(x.sort_value * 3) DESC"
        )

        plan = Plan(parse_one(query))

        self.assertIsInstance(plan.root, Sort)
        self.assertTrue(plan.root.projections)
        self.assertTrue(plan.root.dependencies)
