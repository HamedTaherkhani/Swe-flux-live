import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.qualify import qualify


class TestExpandStarsControlFlow(unittest.TestCase):
    def test_nested_star_modifiers_and_using_join(self):
        width = 18 + sum(i % 3 for i in range(7))
        columns = [f"c{index:02d}" for index in range(width)]
        schema = {
            table: {column: "INT" for column in columns}
            for table in ("base_a", "base_b")
        }

        excluded = columns[3::4][:2]
        join_keys = columns[11:13]
        sql = f"""
            WITH raw_pick AS (
                SELECT
                    * EXCLUDE ({", ".join(excluded)})
                      REPLACE ({columns[1]} + {width * width} AS {columns[1]})
                      RENAME ({columns[2]} AS renamed_{columns[2]})
                FROM base_a
            ),
            side_pick AS (
                SELECT * ILIKE 'c1%' FROM base_b
            ),
            combined AS (
                SELECT a.*, b.* EXCLUDE ({columns[10]})
                FROM raw_pick AS a
                JOIN side_pick AS b USING ({", ".join(join_keys)})
            )
            SELECT * FROM combined
        """

        result = qualify(
            parse_one(sql, read="snowflake"),
            schema=schema,
            dialect="snowflake",
            quote_identifiers=False,
        )

        self.assertIsInstance(result, exp.Select)
        self.assertEqual(len(list(result.find_all(exp.Coalesce))), len(join_keys))
        self.assertGreater(
            max(len(select.selects) for select in result.find_all(exp.Select)),
            len(columns),
        )
