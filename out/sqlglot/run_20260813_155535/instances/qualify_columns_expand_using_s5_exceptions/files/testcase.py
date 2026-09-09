import random
import unittest

from sqlglot import parse_one
from sqlglot.optimizer.qualify import qualify


class TestExpandUsingExceptions(unittest.TestCase):
    def test_generated_join_chain_failure(self):
        rng = random.Random(90210)

        def token(prefix):
            return prefix + "_" + "".join(
                rng.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(7)
            )

        common_columns = [token("key") for _ in range(5)]
        tables = [token("source") for _ in range(20)]
        unavailable_column = token("unavailable")
        schema = {
            table: {
                **{column: "INT" for column in common_columns},
                token("payload"): "INT",
            }
            for table in tables
        }

        joins = []
        for index, table in enumerate(tables[1:-1], 1):
            width = 2 + (index * index + index) % (len(common_columns) - 1)
            offset = index % len(common_columns)
            rotated = common_columns[offset:] + common_columns[:offset]
            joins.append(f"JOIN {table} USING ({', '.join(rotated[:width])})")

        joins.append(
            f"JOIN {tables[-1]} USING ({unavailable_column}, {common_columns[-1]})"
        )
        sql = (
            f"SELECT {', '.join(common_columns)} FROM {tables[0]} " + " ".join(joins)
        )

        error = None
        try:
            qualify(parse_one(sql), schema=schema)
        except BaseException as caught:
            error = caught

        self.assertIsNotNone(error)
        self.assertIsInstance(error, Exception)
        self.assertGreater(len(str(error)), len(unavailable_column))
        self.assertEqual(error.__class__.__module__.split(".")[0], "sqlglot")
