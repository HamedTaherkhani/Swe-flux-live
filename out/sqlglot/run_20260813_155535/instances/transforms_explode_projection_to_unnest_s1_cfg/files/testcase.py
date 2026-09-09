import random
import unittest

import sqlglot
from sqlglot import exp, transforms


class TestExplodeProjectionControlFlow(unittest.TestCase):
    def test_seeded_projection_mix(self):
        rng = random.Random("projection-shuffle")
        projection_kinds = []
        for _ in range(6):
            batch = list(range(7))
            rng.shuffle(batch)
            projection_kinds.extend(batch)

        projections = []
        accumulator = rng.randrange(1000)
        for index, kind in enumerate(projection_kinds):
            accumulator = (accumulator * 37 + rng.randrange(97) + index) % 10007
            suffix = f"{index}_{accumulator}"
            if kind == 0:
                projections.append(f"base_{suffix} AS keep_{suffix}")
            elif kind == 1:
                projections.append(f"EXPLODE(arr_{suffix})")
            elif kind == 2:
                projections.append(f"EXPLODE(arr_{suffix}) AS value_{suffix}")
            elif kind == 3:
                projections.append(f"POSEXPLODE(arr_{suffix})")
            elif kind == 4:
                projections.append(
                    f"POSEXPLODE(arr_{suffix}) AS (position_{suffix}, value_{suffix})"
                )
            elif kind == 5:
                projections.append(f"EXPLODE_OUTER(arr_{suffix})")
            else:
                projections.append(
                    f"POSEXPLODE_OUTER(arr_{suffix}) "
                    f"AS (position_{suffix}, value_{suffix})"
                )

        rich_select = sqlglot.parse_one(
            "SELECT " + ", ".join(projections) + " FROM source_data",
            read="spark",
        )
        empty_select = exp.Select()
        transform = transforms.explode_projection_to_unnest(index_offset=0)

        plain_column = exp.column("untouched")
        self.assertIs(transform(plain_column), plain_column)
        self.assertIs(transform(rich_select), rich_select)
        self.assertFalse(any(selection.find(exp.Explode) for selection in rich_select.selects))
        self.assertGreater(
            len(rich_select.args.get("joins", [])),
            len(projection_kinds) // 2,
        )
        self.assertIsNotNone(rich_select.args.get("where"))
        self.assertIs(transform(empty_select), empty_select)
