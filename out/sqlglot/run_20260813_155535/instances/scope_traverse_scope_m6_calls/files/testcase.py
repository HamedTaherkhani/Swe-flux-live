import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import build_scope, traverse_scope


class TestScopeTraversalCalls(unittest.TestCase):
    def assert_traversable(self, sql, *, dialect=None, build=False):
        expression = parse_one(sql, dialect=dialect)
        if build:
            root = build_scope(expression)
            self.assertIsNotNone(root)
            self.assertIsInstance(root.expression, exp.Expr)
        else:
            scopes = traverse_scope(expression)
            self.assertTrue(scopes)
            self.assertIsInstance(scopes[-1].expression, exp.Expr)

    def test_joined_derived_tables(self):
        branches = [
            f"(SELECT k, v FROM source_{i % 3} WHERE v % 2 = {i % 2}) AS d{i}"
            for i in range(3 * 5)
        ]
        sql = f"SELECT d0.k FROM {branches[0]} " + " ".join(
            f"JOIN {branch} ON d0.k = d{i}.k" for i, branch in enumerate(branches[1:], 1)
        )
        self.assert_traversable(sql)

    def test_cte_dependency_chain(self):
        names = [f"stage_{i}" for i in range(4 * 4)]
        ctes = [f"{names[0]} AS (SELECT id FROM seed_table)"]
        ctes.extend(
            f"{name} AS (SELECT id FROM {names[i - 1]} WHERE id % 3 <> {i % 3})"
            for i, name in enumerate(names[1:], 1)
        )
        self.assert_traversable(f"WITH {', '.join(ctes)} SELECT id FROM {names[-1]}", build=True)

    def test_nested_union_tree(self):
        leaves = [f"SELECT {i % 5} AS n FROM rel_{i % 4}" for i in range(3 * 7)]
        while len(leaves) > 1:
            leaves = [
                f"({left} UNION ALL {right})"
                for left, right in zip(leaves[::2], leaves[1::2])
            ] + leaves[len(leaves) // 2 * 2 :]
        self.assert_traversable(leaves[0])

    def test_scalar_subquery_projection(self):
        projections = [
            f"(SELECT MAX(v) FROM metric_{i % 5} WHERE metric_{i % 5}.k = base.k) AS m{i}"
            for i in range(4 * 5)
        ]
        self.assert_traversable(f"SELECT base.k, {', '.join(projections)} FROM base")

    def test_predicate_subqueries(self):
        predicates = []
        for i in range(3 * 6):
            table = f"lookup_{i % 4}"
            if i % 2:
                predicates.append(f"EXISTS (SELECT 1 FROM {table} WHERE {table}.k = fact.k)")
            else:
                predicates.append(f"fact.k IN (SELECT k FROM {table} WHERE flag = {i % 3})")
        self.assert_traversable("SELECT fact.k FROM fact WHERE " + " OR ".join(predicates))

    def test_create_table_as_ctes(self):
        pieces = [
            f"part_{i} AS (SELECT id FROM raw_{i % 3} WHERE bucket = {i % 4})"
            for i in range(3 * 5)
        ]
        self.assert_traversable(
            f"CREATE TABLE assembled AS WITH {', '.join(pieces)} "
            + " UNION ALL ".join(f"SELECT id FROM part_{i}" for i in range(len(pieces))),
            build=True,
        )

    def test_insert_with_union_source(self):
        selects = [
            f"SELECT id, {i % 3} AS shard FROM ingest_{i % 5}" for i in range(4 * 4)
        ]
        self.assert_traversable(
            "INSERT INTO sink " + " UNION ALL ".join(selects),
            build=True,
        )

    def test_update_from_derived_and_values(self):
        projections = ", ".join(
            f"(SELECT MAX(score) FROM scores_{i % 4} WHERE user_id = target.id) AS s{i}"
            for i in range(3 * 6)
        )
        sql = (
            "UPDATE target SET value = source.s0 "
            f"FROM (SELECT users.id, {projections} FROM users) AS source "
            "WHERE target.id = source.id"
        )
        self.assert_traversable(sql, dialect="postgres")

    def test_merge_with_nested_source(self):
        layers = "SELECT id, value FROM incoming"
        for i in range(3 * 5):
            layers = f"SELECT id, value + {i % 4} AS value FROM ({layers}) AS layer_{i}"
        sql = (
            "MERGE INTO destination AS d "
            f"USING ({layers}) AS s ON d.id = s.id "
            "WHEN MATCHED THEN UPDATE SET value = s.value "
            "WHEN NOT MATCHED THEN INSERT (id, value) VALUES (s.id, s.value)"
        )
        self.assert_traversable(sql)

    def test_lateral_unnest_subqueries(self):
        arrays = ", ".join(
            f"(SELECT ARRAY({i % 3}, {(i + 1) % 5}) FROM array_source_{i % 4})"
            for i in range(4 * 4)
        )
        sql = (
            "SELECT item FROM base "
            f"CROSS JOIN UNNEST(ARRAY({arrays})) AS u(item)"
        )
        self.assert_traversable(sql, dialect="duckdb", build=True)

    def test_recursive_cte_with_companion_ctes(self):
        companions = [
            f"helper_{i} AS (SELECT n FROM helper_source_{i % 3})"
            for i in range(3 * 5)
        ]
        sql = (
            "WITH RECURSIVE seq(n) AS ("
            "SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 7"
            f"), {', '.join(companions)} "
            "SELECT seq.n FROM seq "
            + " ".join(
                f"LEFT JOIN helper_{i} ON helper_{i}.n = seq.n"
                for i in range(len(companions))
            )
        )
        self.assert_traversable(sql)

    def test_parenthesized_query_with_lateral_joins(self):
        joins = " ".join(
            f"LEFT JOIN LATERAL (SELECT value FROM lateral_{i % 4} "
            f"WHERE lateral_{i % 4}.id = root.id) AS l{i} ON TRUE"
            for i in range(3 * 6)
        )
        self.assert_traversable(f"(SELECT root.id FROM root {joins}) LIMIT 7", build=True)
