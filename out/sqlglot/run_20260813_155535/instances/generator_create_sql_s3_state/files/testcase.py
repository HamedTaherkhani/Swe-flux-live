import unittest

from sqlglot import exp
from sqlglot.generator import Generator


class BranchingCreateGenerator(Generator):
    PROPERTIES_LOCATION = {
        **Generator.PROPERTIES_LOCATION,
        exp.ForceProperty: exp.Properties.Location.POST_INDEX,
    }


class CreateSQLProgramStateTest(unittest.TestCase):
    def test_programmatic_create_variants(self):
        width = sum((number * number + 3) % 7 + 1 for number in range(6))
        rounds = width - sum(number % 3 for number in range(5))
        generator = BranchingCreateGenerator(pretty=False)
        outputs = []

        for index in range(rounds):
            offset = sum((index + step * step) % width for step in range(4))
            projections = [
                exp.alias_(
                    exp.column(f"field_{(offset + position * (index + 3)) % width}"),
                    f"metric_{position}_{(offset * 5 + position) % width}",
                )
                for position in range(width)
            ]
            query = exp.select(*projections).from_(
                exp.to_table(f"source_{(offset + index * index) % width}")
            )
            properties = exp.Properties(
                expressions=[
                    exp.TemporaryProperty(),
                    exp.HeapProperty(),
                    exp.LockingProperty(
                        kind="ROW",
                        this=exp.to_table(f"lock_{(offset + index) % width}"),
                        for_or_in="FOR",
                        lock_type="ACCESS",
                        override=(index + offset) % 2 == 0,
                    ),
                    exp.ForceProperty(),
                    exp.OnCommitProperty(delete=(index * 3 + offset) % 4 < 2),
                ]
            )
            create = exp.Create(
                this=exp.to_table(f"view_{(offset * 7 + index) % (width * 2)}"),
                kind="VIEW",
                expression=query,
                properties=properties,
                indexes=[
                    exp.to_identifier(
                        f"idx_{slot}_{(offset + slot * index) % width}"
                    )
                    for slot in range((index % 4) + 1)
                ],
                replace=index % 2 == 0,
                refresh=index % 5 == 1,
                unique=(index * 7) % 4 == 0,
                clustered=(None, True, False)[(index * index + 3) % 3],
                concurrently=index % 3 == 1,
                exists=index % 4 != 1,
                no_schema_binding=index % 6 == 4,
                begin=index % 7 in (2, 4),
                clone=(
                    exp.to_table(f"clone_{(offset * 3 + index) % width}")
                    if index % 3
                    else None
                ),
            )

            outputs.append(generator.create_sql(create))

        self.assertEqual(len(outputs), rounds)
        self.assertTrue(all(output.startswith("CREATE") for output in outputs))
        self.assertEqual(len(set(outputs)), len(outputs))
