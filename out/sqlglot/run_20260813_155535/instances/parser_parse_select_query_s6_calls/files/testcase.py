import random
import unittest

import sqlglot
from sqlglot import exp


class TestParseSelectQueryCalls(unittest.TestCase):
    def test_generated_ctes_and_set_operations(self):
        rng = random.Random(sum(value * value for value in range(19)))
        cte_count = 15 + rng.randrange(5)
        ctes = []

        for index in range(cte_count):
            row_count = 3 + rng.randrange(4)
            rows = []
            for row_index in range(row_count):
                row = tuple(
                    (rng.randrange(113) + index * (column + 1) + row_index) % 127
                    for column in range(3)
                )
                rows.append(f"({row[0]}, {row[1]}, {row[2]})")

            select_mode = ("", "ALL ", "DISTINCT ")[rng.randrange(3)]
            offset = rng.randrange(2, 23)
            divisor = rng.randrange(2, 9)
            body = (
                f"SELECT {select_mode}v.a + {offset} AS score, v.b AS bucket "
                f"FROM (VALUES {', '.join(rows)}) AS v(a, b, c) "
                f"WHERE v.c % {divisor} >= 0 "
                "GROUP BY v.a, v.b HAVING SUM(v.c) >= 0"
            )

            branch = rng.randrange(4)
            if branch == 0:
                body += (
                    f" UNION ALL SELECT n.score + {rng.randrange(1, 8)}, n.bucket "
                    f"FROM (SELECT v2.a AS score, v2.b AS bucket "
                    f"FROM (VALUES {', '.join(reversed(rows))}) AS v2(a, b, c)) AS n"
                )
            elif branch == 1 and index:
                body += (
                    f" UNION SELECT p.score + {rng.randrange(1, 8)}, p.bucket "
                    f"FROM q{index - 1} AS p WHERE p.score IN "
                    f"(SELECT score FROM q{index - 1} WHERE bucket >= 0)"
                )
            elif branch == 2:
                body += f" ORDER BY bucket, score LIMIT {rng.randrange(2, 7)}"

            ctes.append(f"q{index} AS ({body})")

        final_index = cte_count - 1
        query = (
            f"WITH {', '.join(ctes)} "
            f"SELECT outer_q.bucket, SUM(outer_q.score) AS total "
            f"FROM (SELECT score, bucket FROM q{final_index} "
            f"WHERE score IN (SELECT score FROM q{final_index} WHERE bucket >= 0)) AS outer_q "
            "GROUP BY outer_q.bucket ORDER BY total DESC LIMIT 9"
        )

        tree = sqlglot.parse_one(query)

        self.assertIsInstance(tree, exp.Select)
        self.assertEqual(len(tree.args["with_"].expressions), cte_count)
        self.assertGreater(sum(isinstance(node, exp.Select) for node in tree.walk()), cte_count)
        self.assertTrue(tree.sql())
