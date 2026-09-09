import random
import unittest

import sqlglot
from sqlglot import exp
from sqlglot.dialects import Dialect


class TestGeneratorOrderedDataFlow(unittest.TestCase):
    def test_seeded_ordering_contexts(self):
        rng = random.Random(1618033)
        builders = (
            ("bigquery", lambda c, a: f"SELECT ARRAY_AGG({c} ORDER BY {c} ASC NULLS LAST) FROM t"),
            ("bigquery", lambda c, a: f"SELECT RANK() OVER (ORDER BY {c} ASC NULLS LAST) FROM t"),
            (
                "bigquery",
                lambda c, a: (
                    f"SELECT RANK() OVER (ORDER BY {c} ASC NULLS LAST "
                    "RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t"
                ),
            ),
            (
                "bigquery",
                lambda c, a: (
                    f"SELECT LAST_VALUE({c} IGNORE NULLS) OVER (ORDER BY {c} ASC NULLS LAST) FROM t"
                ),
            ),
            ("bigquery", lambda c, a: f"SELECT SUM({c}) OVER (ORDER BY {c} ASC NULLS LAST) FROM t"),
            ("mysql", lambda c, a: f"SELECT {c} FROM t ORDER BY {c} ASC NULLS LAST"),
            ("mysql", lambda c, a: f"SELECT {c} FROM t ORDER BY 1 ASC NULLS LAST"),
            ("mysql", lambda c, a: f"SELECT {c} FROM t ORDER BY RAND() ASC NULLS LAST"),
            ("tsql", lambda c, a: f"SELECT {c} AS {a} FROM t ORDER BY {a} ASC NULLS LAST"),
            ("clickhouse", lambda c, a: f"SELECT {c} FROM t ORDER BY {c} WITH FILL"),
            ("postgres", lambda c, a: f"SELECT {c} FROM t ORDER BY {c} DESC NULLS FIRST"),
        )
        rounds = len(builders) * 5 + len(builders) // 2
        schedule = [index % len(builders) for index in range(rounds)]
        rng.shuffle(schedule)

        outputs = []
        for position, builder_index in enumerate(schedule):
            dialect_name, build_sql = builders[builder_index]
            salt = rng.randrange(1000, 9000)
            column = f"c_{position}_{salt % 211}"
            alias = f"a_{(salt * 7 + position) % 193}"
            tree = sqlglot.parse_one(build_sql(column, alias), read=dialect_name)
            ordered = next(tree.find_all(exp.Ordered))
            generator = Dialect.get_or_raise(dialect_name).generator(unsupported_level="ignore")
            outputs.append(generator.ordered_sql(ordered))

        self.assertEqual(len(outputs), rounds)
        self.assertTrue(all(output and isinstance(output, str) for output in outputs))
        self.assertGreater(len(set(outputs)), len(builders) * 3)
