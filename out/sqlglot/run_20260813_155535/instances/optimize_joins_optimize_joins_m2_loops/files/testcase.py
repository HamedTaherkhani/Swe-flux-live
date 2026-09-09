import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.optimize_joins import optimize_joins


class TestOptimizeJoinsLoopDynamics(unittest.TestCase):
    def _build_select(
        self,
        rng: random.Random,
        index: int,
        group_span: int,
        dependency_span: int,
        complexity: int,
        blocked: bool,
    ) -> str:
        base = f"b{index}"
        group_count = 2 + rng.randrange(group_span)
        dependency_count = 3 + rng.randrange(dependency_span)
        crosses = [f"c{index}_{group}" for group in range(group_count)]
        clauses = [f"CROSS JOIN source_{name} AS {name}" for name in crosses]

        for dependency in range(dependency_count):
            alias = f"d{index}_{dependency}"
            selected = rng.sample(crosses, 1 + rng.randrange(group_count))
            predicates = [
                f"{alias}.key_{position} = {name}.key_{position}"
                for position, name in enumerate(selected)
            ]
            predicates.append(f"{alias}.base_key = {base}.base_key")
            predicates.extend(
                f"{alias}.payload_{term} = {base}.payload_{(term + dependency) % (complexity + 1)}"
                for term in range(1 + rng.randrange(complexity))
            )

            if (dependency + index + complexity) % 4 == 0:
                on = f"({predicates[0]} OR {predicates[1]})"
            else:
                rng.shuffle(predicates)
                on = " AND ".join(predicates)

            join_kind = "LEFT JOIN" if blocked and dependency == 0 else "JOIN"
            clauses.append(f"{join_kind} fact_{alias} AS {alias} ON {on}")

        return f"SELECT {base}.base_key FROM base_{index} AS {base} {' '.join(clauses)}"

    def _exercise(
        self,
        seed: int,
        select_count: int,
        group_span: int,
        dependency_span: int,
        complexity: int,
        blocked: bool = False,
    ) -> None:
        rng = random.Random(seed * seed + select_count * complexity)
        sql = " UNION ALL ".join(
            self._build_select(
                rng,
                index,
                group_span,
                dependency_span,
                complexity,
                blocked and index % 2 == 0,
            )
            for index in range(select_count)
        )
        expression = parse_one(sql)
        result = optimize_joins(expression)

        self.assertIs(result, expression)
        self.assertEqual(sum(1 for _ in result.find_all(exp.Select)), select_count)
        self.assertTrue(result.sql())

    def test_01_compact_dependencies(self):
        self._exercise(3, 1, 2, 3, 2)

    def test_02_wide_cross_groups(self):
        self._exercise(5, 2, 3, 3, 3)

    def test_03_dense_predicates(self):
        self._exercise(7, 1, 4, 4, 4)

    def test_04_many_select_scopes(self):
        self._exercise(2, 3, 2, 3, 3)

    def test_05_sparse_dependency_choices(self):
        self._exercise(8, 2, 2, 4, 2)

    def test_06_mixed_outer_join_scopes(self):
        self._exercise(4, 3, 3, 3, 3, blocked=True)

    def test_07_all_scopes_blocked(self):
        self._exercise(6, 1, 5, 5, 5, blocked=True)

    def test_08_deep_conjunctions(self):
        self._exercise(9, 2, 3, 4, 5)

    def test_09_repeated_small_scopes(self):
        self._exercise(1, 3, 2, 2, 2)

    def test_10_broad_dependency_fanout(self):
        self._exercise(3, 2, 5, 5, 3)

    def test_11_alternating_predicate_shapes(self):
        self._exercise(7, 2, 4, 3, 4)

    def test_12_single_large_scope(self):
        self._exercise(5, 1, 6, 6, 5)
