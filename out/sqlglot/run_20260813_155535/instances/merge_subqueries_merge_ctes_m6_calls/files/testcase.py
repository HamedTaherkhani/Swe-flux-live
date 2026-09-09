import random
import unittest

from sqlglot import parse_one
from sqlglot.optimizer.merge_subqueries import merge_ctes
from sqlglot.optimizer.scope import traverse_scope


def generated_columns(rng, alias, size):
    return ", ".join(
        f"{alias}.c{index} + {rng.randrange(2, 97)} AS v{index}" for index in range(size)
    )


def cte_chain(seed, depth, projection_size):
    rng = random.Random(seed)
    ctes = []
    source = f"raw_{rng.randrange(1000, 9000)}"
    for level in range(depth):
        name = f"stage_{level}"
        ctes.append(
            f"{name} AS (SELECT {generated_columns(rng, 's', projection_size)} "
            f"FROM {source} AS s WHERE s.flag <> {rng.randrange(2, 11)})"
        )
        source = name
    return f"WITH {', '.join(ctes)} SELECT q.v0 FROM {source} AS q"


class TestMergeCtesInvocationCounts(unittest.TestCase):
    def run_merge(self, sql, *, isolated=False, provide_scopes=False):
        expression = parse_one(sql)
        scopes = traverse_scope(expression) if provide_scopes else None
        result, merged = merge_ctes(expression, isolated, scopes=scopes)
        self.assertIs(result, expression)
        self.assertTrue(result.sql())
        self.assertTrue(all(node.parent is not None for node in result.iter_expressions()))
        return merged

    def test_seeded_linear_chain(self):
        sql = cte_chain(0xA17, 7, 4)
        self.assertTrue(self.run_merge(sql))

    def test_precomputed_scope_chain(self):
        sql = cte_chain(0xB28, 5, 6)
        self.assertTrue(self.run_merge(sql, provide_scopes=True))

    def test_reused_cte_is_retained(self):
        rng = random.Random(0xC39)
        name = f"shared_{rng.randrange(100, 999)}"
        sql = (
            f"WITH {name} AS (SELECT x.k, x.v FROM base_{rng.randrange(1000, 9000)} AS x) "
            f"SELECT a.k FROM {name} AS a JOIN {name} AS b ON a.k = b.k"
        )
        self.assertFalse(self.run_merge(sql))

    def test_mixed_reused_and_singular(self):
        rng = random.Random(0xD4A)
        shared = f"shared_{rng.randrange(100, 999)}"
        single = f"single_{rng.randrange(100, 999)}"
        sql = (
            f"WITH {shared} AS (SELECT k FROM raw_{rng.randrange(1000, 9000)}), "
            f"{single} AS (SELECT k, v FROM raw_{rng.randrange(1000, 9000)}) "
            f"SELECT s.v FROM {single} AS s JOIN {shared} AS a ON s.k = a.k "
            f"JOIN {shared} AS b ON a.k = b.k"
        )
        self.assertTrue(self.run_merge(sql))

    def test_aggregate_projection_blocks_merge(self):
        rng = random.Random(0xE5B)
        ctes = [
            f"a{index} AS (SELECT k, SUM(v + {rng.randrange(1, 23)}) AS total "
            f"FROM raw_{rng.randrange(1000, 9000)} GROUP BY k)"
            for index in range(4)
        ]
        sql = f"WITH {', '.join(ctes)} SELECT q.total FROM a3 AS q"
        self.assertFalse(self.run_merge(sql))

    def test_distinct_and_limit_candidates(self):
        rng = random.Random(0xF6C)
        ctes = []
        for index in range(6):
            modifier = "DISTINCT " if index % 2 else ""
            suffix = f" LIMIT {rng.randrange(2, 19)}" if index % 3 == 0 else ""
            ctes.append(
                f"d{index} AS (SELECT {modifier}k, v FROM "
                f"raw_{rng.randrange(1000, 9000)}{suffix})"
            )
        sql = f"WITH {', '.join(ctes)} SELECT q.v FROM d4 AS q"
        self.assertTrue(self.run_merge(sql))

    def test_isolated_joined_sources(self):
        rng = random.Random(0x107D)
        name = f"iso_{rng.randrange(100, 999)}"
        sql = (
            f"WITH {name} AS (SELECT k, v FROM raw_{rng.randrange(1000, 9000)}) "
            f"SELECT q.v FROM {name} AS q JOIN guard_{rng.randrange(1000, 9000)} AS g "
            "ON q.k = g.k"
        )
        self.assertFalse(self.run_merge(sql, isolated=True))

    def test_where_order_and_hints(self):
        rng = random.Random(0x118E)
        name = f"ordered_{rng.randrange(100, 999)}"
        sql = (
            f"WITH {name} AS (SELECT /*+ BROADCAST(x) */ x.k, x.v "
            f"FROM raw_{rng.randrange(1000, 9000)} AS x "
            f"WHERE x.v > {rng.randrange(20, 80)} ORDER BY x.k) "
            f"SELECT q.v FROM {name} AS q"
        )
        self.assertTrue(self.run_merge(sql))

    def test_inner_join_fanout(self):
        rng = random.Random(0x129F)
        joins = " ".join(
            f"JOIN lookup_{rng.randrange(1000, 9000)} AS j{index} "
            f"ON b.k = j{index}.k AND j{index}.flag = {rng.randrange(2, 7)}"
            for index in range(5)
        )
        sql = (
            f"WITH fan AS (SELECT b.k, b.v FROM base_{rng.randrange(1000, 9000)} AS b "
            f"{joins}) SELECT q.v FROM fan AS q"
        )
        self.assertTrue(self.run_merge(sql))

    def test_source_name_collision(self):
        rng = random.Random(0x13A0)
        colliding = f"src_{rng.randrange(100, 999)}"
        sql = (
            f"WITH wrapped AS (SELECT i.k, i.v FROM "
            f"raw_{rng.randrange(1000, 9000)} AS {colliding} "
            f"JOIN inner_{rng.randrange(1000, 9000)} AS i ON {colliding}.k = i.k) "
            f"SELECT q.v FROM wrapped AS q JOIN outer_{rng.randrange(1000, 9000)} "
            f"AS {colliding} ON q.k = {colliding}.k"
        )
        self.assertTrue(self.run_merge(sql))

    def test_left_join_with_inner_filter(self):
        rng = random.Random(0x14B1)
        name = f"filtered_{rng.randrange(100, 999)}"
        sql = (
            f"WITH {name} AS (SELECT x.k, x.v FROM raw_{rng.randrange(1000, 9000)} AS x "
            f"WHERE x.v > {rng.randrange(5, 55)}) "
            f"SELECT g.k FROM guard_{rng.randrange(1000, 9000)} AS g LEFT JOIN {name} AS q "
            "ON g.k = q.k"
        )
        self.assertFalse(self.run_merge(sql))

    def test_numeric_group_and_regular_cte(self):
        rng = random.Random(0x15C2)
        sql = (
            f"WITH numbered AS (SELECT {rng.randrange(2, 9)} AS ordinal, x.k "
            f"FROM raw_{rng.randrange(1000, 9000)} AS x), "
            f"plain AS (SELECT y.k, y.v + {rng.randrange(3, 31)} AS adjusted "
            f"FROM raw_{rng.randrange(1000, 9000)} AS y) "
            "SELECT p.adjusted FROM plain AS p JOIN numbered AS n ON p.k = n.k "
            "GROUP BY p.adjusted, ROLLUP(n.ordinal)"
        )
        self.assertTrue(self.run_merge(sql))
