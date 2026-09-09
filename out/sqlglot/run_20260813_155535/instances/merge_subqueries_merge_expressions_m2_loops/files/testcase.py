import random
import unittest

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.merge_subqueries import merge_subqueries


class TestMergeExpressionsLoops(unittest.TestCase):
    def _exercise(self, label, variant, mode, use_cte=False):
        seed = sum((index + 1) * ord(character) for index, character in enumerate(label))
        rng = random.Random(seed)
        width = 4 + variant % 4
        depth = 1

        base_projections = []
        for index in range(width):
            factor = 1 + rng.randrange(7)
            offset = rng.randrange(9)
            base_projections.append(
                f"s.c{(index + variant) % 7} * {factor} + {offset} AS p{index}"
            )
        query = f"SELECT {', '.join(base_projections)} FROM source_{label} AS s"

        for level in range(depth):
            alias = f"q_{label}_{level}"
            projections = []
            for index in range(width):
                source_index = (index + rng.randrange(width)) % width
                repeat_count = 2 + rng.randrange(6)
                reference = f"{alias}.p{source_index}"

                if mode == "direct" and (index + level) % 2:
                    value = reference
                elif mode == "unary" and (index + level) % 3 == 0:
                    value = f"-{reference}"
                elif mode == "function" and (index + level) % 2 == 0:
                    value = f"COALESCE({', '.join(reference for _ in range(repeat_count))})"
                else:
                    value = " + ".join(reference for _ in range(repeat_count))
                projections.append(f"{value} AS p{index}")

            predicates = []
            for offset in range(1 + rng.randrange(4)):
                column = (offset * 2 + level + variant) % width
                predicates.append(f"{alias}.p{column} >= {rng.randrange(9)}")

            query = (
                f"SELECT {', '.join(projections)} FROM ({query}) AS {alias} "
                f"WHERE {' AND '.join(predicates)}"
            )

        if use_cte:
            cte = f"cte_{label}"
            references = [
                f"{cte}.p{(index + variant) % width}" for index in range(width)
            ]
            query = (
                f"WITH {cte} AS ({query}) "
                f"SELECT {', '.join(references)} FROM {cte}"
            )

        tree = sqlglot.parse_one(query)
        selects_before = sum(isinstance(node, exp.Select) for node in tree.walk())
        optimized = merge_subqueries(tree)
        selects_after = sum(isinstance(node, exp.Select) for node in optimized.walk())

        self.assertGreater(selects_before, selects_after)
        self.assertIsInstance(optimized, exp.Select)
        self.assertTrue(optimized.sql())

    def test_amber_binary_derived(self):
        self._exercise("amber", 1, "binary")

    def test_birch_unary_derived(self):
        self._exercise("birch", 2, "unary")

    def test_cobalt_function_derived(self):
        self._exercise("cobalt", 3, "function")

    def test_dahlia_direct_derived(self):
        self._exercise("dahlia", 4, "direct")

    def test_elm_binary_cte(self):
        self._exercise("elm", 5, "binary", use_cte=True)

    def test_fir_function_cte(self):
        self._exercise("fir", 6, "function", use_cte=True)

    def test_garnet_unary_cte(self):
        self._exercise("garnet", 7, "unary", use_cte=True)

    def test_hazel_direct_cte(self):
        self._exercise("hazel", 8, "direct", use_cte=True)

    def test_indigo_binary_derived(self):
        self._exercise("indigo", 3, "binary")

    def test_juniper_function_derived(self):
        self._exercise("juniper", 6, "function")

    def test_kelp_unary_derived(self):
        self._exercise("kelp", 5, "unary")

    def test_lilac_binary_cte(self):
        self._exercise("lilac", 2, "binary", use_cte=True)
