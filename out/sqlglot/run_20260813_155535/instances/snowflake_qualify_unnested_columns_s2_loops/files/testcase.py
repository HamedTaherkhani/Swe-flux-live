import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.generators.snowflake import _qualify_unnested_columns


class TestSnowflakeQualifyUnnestedColumnsLoops(unittest.TestCase):
    def test_generated_mixed_unnest_columns(self):
        rng = random.Random(sum(i * i + 3 * i for i in range(2 * 5)))
        field_names = [
            f"field_{i}_{(i * i + 7 * i + 5) % 23}" for i in range(4 * 5 - 3)
        ]

        unnests = []
        for unnest_index in range(2 * 3):
            properties = ", ".join(
                f"{unnest_index * 100 + field_index} AS "
                f"{field_names[(field_index * 5 + unnest_index * 3) % len(field_names)]}"
                for field_index in range(5 + unnest_index % 4)
            )
            alias = f" AS source_{unnest_index}" if unnest_index % 2 else ""
            unnests.append(f"UNNEST([1, 2, STRUCT({properties})]){alias}")

        selected_indices = [
            index
            for index in range(3 * 4 * 5)
            if rng.randrange(7) not in (0, 2)
        ]
        projections = []
        for position, index in enumerate(selected_indices):
            field = field_names[(index * index + 3 * position + 1) % len(field_names)]
            if position % 7 == 0:
                projection = f"source_1.{field}"
            elif position % 5 == 0:
                projection = f"unknown_{(index * 11 + position) % 29}"
            else:
                projection = field

            if position % 4 == 0:
                other = field_names[(index + position * 2 + 3) % len(field_names)]
                projection = f"COALESCE({projection}, {other}) AS generated_{position}"
            projections.append(projection)

        expression = parse_one(
            f"SELECT {', '.join(projections)} FROM {', '.join(unnests)}",
            dialect="bigquery",
        )
        result = _qualify_unnested_columns(expression)

        columns = list(result.find_all(exp.Column))
        self.assertIs(result, expression)
        self.assertTrue(any(column.table for column in columns))
        self.assertTrue(any(not column.table for column in columns))
        self.assertTrue(all(unnest.args.get("alias") for unnest in result.find_all(exp.Unnest)))
