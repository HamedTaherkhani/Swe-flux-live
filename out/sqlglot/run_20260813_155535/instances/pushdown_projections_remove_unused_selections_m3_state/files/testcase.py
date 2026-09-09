import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.pushdown_projections import pushdown_projections


class TestRemoveUnusedSelectionsState(unittest.TestCase):
    def _optimize(self, sql, schema=None):
        tree = parse_one(sql)
        result = pushdown_projections(tree, schema=schema)
        self.assertIs(result, tree)
        self.assertTrue(result.find_all(exp.Select))
        self.assertIn("SELECT", result.sql())

    def _projections(self, seed, count, prefix):
        rng = random.Random(seed)
        return [
            f"(src.f_{rng.randrange(17)} + {rng.randrange(2, 31)}) AS {prefix}_{index}"
            for index in range(count)
        ]

    def test_nested_subset(self):
        projections = self._projections(101, 4, "alpha")
        requested = [f"q.alpha_{index}" for index in range(4) if index % 3 != 1]
        self._optimize(
            f"SELECT {', '.join(requested)} FROM "
            f"(SELECT {', '.join(projections)} FROM source AS src) AS q"
        )

    def test_order_alias_retention(self):
        projections = self._projections(203, 4, "ordered")
        order_aliases = [f"ordered_{index}" for index in range(4) if index % 2]
        self._optimize(
            f"SELECT q.ordered_0 FROM "
            f"(SELECT {', '.join(projections)} FROM source AS src "
            f"ORDER BY {', '.join(reversed(order_aliases))}) AS q"
        )

    def test_aggregate_fallback(self):
        rng = random.Random(307)
        projections = [
            f"SUM(src.f_{rng.randrange(17)} * {index + 2}) AS total_{index}"
            for index in range(4)
        ]
        self._optimize(
            f"SELECT q.total_2 FROM "
            f"(SELECT {', '.join(projections)} FROM source AS src) AS q"
        )

    def test_star_resolution(self):
        fields = {f"f_{index}": "INT" for index in range(9)}
        chosen = [f"q.f_{index}" for index in range(9) if (index * index + 3) % 5 < 2]
        self._optimize(
            f"SELECT {', '.join(chosen)} FROM (SELECT * FROM source AS src) AS q",
            schema={"source": fields},
        )

    def test_group_by_ordinal(self):
        projections = self._projections(409, 4, "grouped")
        self._optimize(
            f"SELECT q.grouped_3 FROM "
            f"(SELECT {', '.join(projections)} FROM source AS src GROUP BY 2, 4) AS q"
        )

    def test_implicit_group_by_all(self):
        rng = random.Random(503)
        dimensions = [
            f"src.f_{rng.randrange(17)} + {index} AS dimension_{index}" for index in range(3)
        ]
        aggregate = f"MAX(src.f_{rng.randrange(17)}) AS aggregate_value"
        self._optimize(
            f"SELECT q.aggregate_value FROM "
            f"(SELECT {', '.join(dimensions + [aggregate])} "
            f"FROM source AS src GROUP BY ALL) AS q"
        )

    def test_set_returning_projection(self):
        values = [str((index + 3) * (index % 4 + 2)) for index in range(8)]
        self._optimize(
            "SELECT q.anchor FROM ("
            "SELECT src.f_1 AS anchor, "
            f"UNNEST(ARRAY({', '.join(values)})) AS expanded, "
            "src.f_2 AS disposable FROM source AS src"
            ") AS q"
        )

    def test_distinct_inner_scope(self):
        projections = self._projections(607, 16, "distinctive")
        self._optimize(
            f"SELECT q.distinctive_1 FROM "
            f"(SELECT DISTINCT {', '.join(projections)} FROM source AS src) AS q"
        )

    def test_union_all_branches(self):
        left = self._projections(701, 3, "left_side")
        right = self._projections(709, 3, "right_side")
        self._optimize(
            "SELECT u.left_side_2 FROM ("
            f"SELECT {', '.join(left)} FROM source AS src UNION ALL "
            f"SELECT {', '.join(right)} FROM source AS src"
            ") AS u"
        )

    def test_cte_column_aliases(self):
        projections = self._projections(809, 4, "inside")
        aliases = [f"renamed_{(index * 5 + 1) % 11}" for index in range(4)]
        self._optimize(
            f"WITH generated({', '.join(aliases)}) AS "
            f"(SELECT {', '.join(projections)} FROM source AS src) "
            f"SELECT generated.{aliases[-1]} FROM generated"
        )

    def test_three_level_chain(self):
        projections = self._projections(907, 4, "deep")
        middle = [
            f"inner_q.deep_{index} * {index + 2} AS middle_{index}" for index in range(4)
        ]
        requested = [f"outer_q.middle_{index}" for index in range(4) if index % 3 == 0]
        self._optimize(
            f"SELECT {', '.join(requested)} FROM ("
            f"SELECT {', '.join(middle)} FROM ("
            f"SELECT {', '.join(projections)} FROM source AS src"
            ") AS inner_q"
            ") AS outer_q"
        )

    def test_window_and_order_dependencies(self):
        rng = random.Random(1009)
        projections = [
            "SUM(src.f_{field}) OVER (PARTITION BY src.f_{partition} "
            "ORDER BY src.f_{ordering}) AS windowed_{index}".format(
                field=rng.randrange(17),
                partition=rng.randrange(17),
                ordering=rng.randrange(17),
                index=index,
            )
            for index in range(3)
        ]
        projections.append("src.f_0 AS plain_value")
        self._optimize(
            f"SELECT q.windowed_1 FROM "
            f"(SELECT {', '.join(projections)} FROM source AS src) AS q"
        )
