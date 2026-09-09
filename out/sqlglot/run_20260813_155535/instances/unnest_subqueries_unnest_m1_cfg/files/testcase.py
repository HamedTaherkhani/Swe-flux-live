import random
import unittest

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.unnest_subqueries import unnest_subqueries as rewrite_subqueries


class TestUnnestControlFlow(unittest.TestCase):
    def _case_count(self, salt):
        return 13 + sum((index * salt) % 3 for index in range(6))

    def _rewrite_all(self, statements):
        rewritten = [rewrite_subqueries(sqlglot.parse_one(sql)) for sql in statements]
        self.assertTrue(rewritten)
        self.assertTrue(all(isinstance(tree, exp.Expr) and tree.sql() for tree in rewritten))
        return rewritten

    def test_scalar_predicates(self):
        rng = random.Random(72617)
        statements = []
        operators = ("=", "<", ">", "<=", ">=")
        for index in range(self._case_count(5)):
            suffix = rng.randrange(10**2, 999)
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a "
                f"{operators[index % len(operators)]} "
                f"(SELECT SUM(y{suffix}.v) AS v FROM y{suffix})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Join) for tree in trees))

    def test_grouped_scalar_projections(self):
        rng = random.Random(104729)
        statements = []
        for index in range(self._case_count(7)):
            suffix = rng.randrange(1000, 9000)
            statements.append(
                f"SELECT x{suffix}.k, x{suffix}.a > "
                f"(SELECT SUM(y{suffix}.v) AS v FROM y{suffix}) AS s{index} "
                f"FROM x{suffix} GROUP BY x{suffix}.k, x{suffix}.a"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Max) and tree.find(exp.Join) for tree in trees))

    def test_grouped_exists_projections(self):
        rng = random.Random(130363)
        statements = []
        for index in range(self._case_count(8)):
            suffix = rng.randrange(200, 9800)
            truth = "TRUE" if (index * index + suffix) % 3 else "FALSE"
            statements.append(
                f"SELECT EXISTS(SELECT {index + 1} WHERE {truth}) AS e{index} "
                f"FROM x{suffix} GROUP BY x{suffix}.k"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Join) and tree.find(exp.Is) for tree in trees))

    def test_in_predicates(self):
        rng = random.Random(155921)
        statements = []
        for index in range(self._case_count(10)):
            suffix = rng.randrange(300, 9900)
            statements.append(
                f"SELECT x{suffix}.a FROM x{suffix} WHERE x{suffix}.a IN "
                f"(SELECT y{suffix}.v AS v FROM y{suffix} WHERE y{suffix}.k > {index % 7})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Join) and not tree.find(exp.In) for tree in trees))

    def test_grouped_in_predicates(self):
        rng = random.Random(179424673)
        statements = []
        for index in range(self._case_count(11)):
            suffix = rng.randrange(400, 9600)
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a IN "
                f"(SELECT MAX(y{suffix}.v) AS v FROM y{suffix} "
                f"GROUP BY y{suffix}.k, y{suffix}.g{index % 4})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(sum(1 for _ in tree.find_all(exp.Select)) >= 3 for tree in trees))

    def test_aggregate_in_predicates(self):
        rng = random.Random(2038074743)
        statements = []
        functions = ("MAX", "MIN", "SUM")
        for index in range(self._case_count(13)):
            suffix = rng.randrange(500, 9500)
            function = functions[(suffix + index) % len(functions)]
            statements.append(
                f"SELECT * FROM x{suffix} WHERE {index + 2} IN "
                f"(SELECT {function}(y{suffix}.v) AS v FROM y{suffix})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Join) for tree in trees))

    def test_any_predicates(self):
        rng = random.Random(22801763489)
        statements = []
        operators = ("=", ">", "<", "<>")
        for index in range(self._case_count(14)):
            suffix = rng.randrange(600, 9400)
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a "
                f"{operators[(suffix + index) % len(operators)]} ANY "
                f"(SELECT y{suffix}.v AS v FROM y{suffix})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(any(tree.find(exp.Join) for tree in trees))
        self.assertTrue(any(tree.find(exp.Any) for tree in trees))

    def test_limited_and_offset_predicates(self):
        rng = random.Random(2521008887)
        statements = []
        for index in range(self._case_count(16)):
            suffix = rng.randrange(700, 9300)
            boundary = 1 + (suffix + index) % 9
            limiter = f"LIMIT {boundary}" if index % 2 else f"OFFSET {boundary}"
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a IN "
                f"(SELECT y{suffix}.v AS v FROM y{suffix} {limiter})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Subquery) for tree in trees))

    def test_multi_projection_subqueries(self):
        rng = random.Random(275604541)
        statements = []
        for index in range(self._case_count(17)):
            suffix = rng.randrange(800, 9200)
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a IN "
                f"(SELECT y{suffix}.v AS v, y{suffix}.k AS k{index} FROM y{suffix})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Subquery) for tree in trees))

    def test_not_in_predicates(self):
        rng = random.Random(29996224275833)
        statements = []
        for index in range(self._case_count(7 * 3 + 1)):
            suffix = rng.randrange(900, 9100)
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a NOT IN "
                f"(SELECT y{suffix}.v AS v FROM y{suffix} WHERE y{suffix}.k <> {index + 3})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Not) and tree.find(exp.Subquery) for tree in trees))

    def test_union_in_predicates(self):
        rng = random.Random(32416190071)
        statements = []
        for index in range(self._case_count(20)):
            suffix = rng.randrange(1000, 9000)
            union_kind = "UNION ALL" if (suffix + index) % 2 else "UNION"
            statements.append(
                f"SELECT * FROM x{suffix} WHERE x{suffix}.a IN "
                f"(SELECT y{suffix}.v AS v FROM y{suffix} {union_kind} "
                f"SELECT z{suffix}.v AS v FROM z{suffix})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.find(exp.Union) and tree.find(exp.Join) for tree in trees))

    def test_join_clause_predicates(self):
        rng = random.Random(3486784401)
        statements = []
        for index in range(self._case_count(22)):
            suffix = rng.randrange(1100, 8900)
            statements.append(
                f"SELECT x{suffix}.a FROM x{suffix} JOIN q{suffix} ON "
                f"x{suffix}.a IN (SELECT y{suffix}.v AS v FROM y{suffix} "
                f"WHERE y{suffix}.k >= {index % 6})"
            )
        trees = self._rewrite_all(statements)
        self.assertTrue(all(tree.args.get("where") and len(tree.args.get("joins") or []) > 1 for tree in trees))
