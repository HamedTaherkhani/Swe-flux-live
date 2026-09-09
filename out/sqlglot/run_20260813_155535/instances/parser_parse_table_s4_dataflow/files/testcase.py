import random
import unittest

import sqlglot
from sqlglot import exp


class TestParseTableDataFlow(unittest.TestCase):
    def test_generated_table_forms(self):
        rng = random.Random(271828)
        forms = [
            ("SELECT * FROM {table}", None),
            ("SELECT * FROM {table} AS {alias}", None),
            ("SELECT * FROM {table} TABLESAMPLE BERNOULLI ({sample} PERCENT)", "postgres"),
            ("SELECT * FROM ONLY {table}", "postgres"),
            ("SELECT * FROM (SELECT * FROM {table}) AS {alias}", None),
            ("SELECT * FROM UNNEST(ARRAY[{left}, {right}]) AS {alias}(x)", "postgres"),
            ("SELECT * FROM (VALUES ({left}), ({right})) AS {alias}(x)", None),
            ("SELECT * FROM {table} WITH ORDINALITY", "postgres"),
            ("SELECT * FROM {table} NOT INDEXED", "sqlite"),
            ("SELECT * FROM {table} INDEXED BY {index}", "sqlite"),
            ("SELECT * FROM {table} FOR SYSTEM_TIME AS OF '{date}'", "mysql"),
        ]
        order = list(range(len(forms)))
        rng.shuffle(order)

        statements = []
        for position in range(44):
            template, dialect = forms[order[position % len(order)]]
            salt = rng.randrange(1000, 9000)
            sql = template.format(
                table=f"t_{position}_{salt}",
                alias=f"a_{salt % 97}_{position}",
                index=f"idx_{salt % 89}",
                sample=1 + salt % 91,
                left=salt % 31,
                right=(salt * 7 + position) % 43,
                date=f"20{10 + salt % 15:02d}-{1 + position % 12:02d}-{1 + salt % 27:02d}",
            )
            statements.append(sqlglot.parse_one(sql, read=dialect))

        self.assertTrue(all(isinstance(statement, exp.Select) for statement in statements))
        self.assertEqual(len({statement.sql() for statement in statements}), len(statements))
