import random
import unittest

import sqlglot
from sqlglot.optimizer.qualify_tables import qualify_tables


class TestQualifyTablesControlFlow(unittest.TestCase):
    def test_generated_scope_forest(self):
        seed_source = random.Random(sum(ord(c) for c in self.id()))
        specs = [
            (seed_source.randrange(1_000_000), width, canonical)
            for width, canonical in ((17, False), (23, True), (19, False))
        ]
        callback_batches = []

        for seed, width, canonical in specs:
            rng = random.Random(seed)
            ctes = []
            cte_names = []
            for index in range(width):
                suffix = f"{index}_{rng.randrange(1000):03d}"
                cte_name = f"q_{suffix}"
                table_name = f"raw_{suffix}"
                cte_names.append(cte_name)

                branch = (index + rng.randrange(5)) % 4
                if branch == 0:
                    body = f"SELECT a_{index}.k FROM {table_name} AS a_{index}"
                elif branch == 1:
                    body = f"SELECT {table_name}.k FROM {table_name}"
                elif branch == 2:
                    body = (
                        f"SELECT d_{index}.k FROM "
                        f"(SELECT n_{index}.k FROM {table_name} AS n_{index}) AS d_{index}"
                    )
                else:
                    values = ", ".join(f"({rng.randrange(1, 10000)})" for _ in range(3))
                    body = f"SELECT v_{index}.k FROM (VALUES {values}) AS v_{index}(k)"
                ctes.append(f"{cte_name} AS ({body})")

            joins = [f"{cte_names[0]} AS root_source"]
            for index, name in enumerate(cte_names[1:], start=1):
                if (index + rng.randrange(7)) % 3:
                    joins.append(f"LEFT JOIN {name} AS j_{index} ON j_{index}.k = root_source.k")
                else:
                    joins.append(f"CROSS JOIN {name}")

            expression = sqlglot.parse_one(
                f"WITH {', '.join(ctes)} SELECT root_source.k FROM {' '.join(joins)}"
            )
            qualified = []
            database = "".join(chr(ord("a") + (seed // (position + 3)) % 26) for position in range(4))
            catalog = database[::-1] + chr(ord("a") + width % 26)
            result = qualify_tables(
                expression,
                db=database,
                catalog=catalog,
                on_qualify=qualified.append,
                canonicalize_table_aliases=canonical,
            )

            self.assertIs(result, expression)
            self.assertTrue(qualified)
            self.assertTrue(all(table.args.get("db") for table in qualified))
            self.assertIn(database, result.sql())
            callback_batches.append(qualified)

        self.assertTrue(all(callback_batches))
        self.assertNotEqual(len(callback_batches[0]), len(callback_batches[1]))
