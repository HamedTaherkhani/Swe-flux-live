import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.generators.duckdb import connect_by_to_recursive_cte


class TestDuckDBConnectByDataFlow(unittest.TestCase):
    def test_seeded_recursive_cte_variants(self):
        label = "recursive-connect-branch-matrix"
        seed = sum((index + 3) * ord(char) for index, char in enumerate(label))
        rng = random.Random(seed)
        transformed_queries = []

        for scenario in range(4):
            column_count = 18 + rng.randrange(8)
            columns = list(range(column_count))
            rng.shuffle(columns)
            projections = [
                f"CONNECT_BY_ROOT metric_{column} AS inherited_{position}"
                for position, column in enumerate(columns)
            ]
            if scenario % 2 == 0:
                projections.insert(rng.randrange(len(projections) + 1), "*")
            if scenario in (0, 3):
                projections.insert(rng.randrange(len(projections) + 1), "LEVEL")

            prefix = (
                f"WITH aux_{scenario} AS (SELECT {scenario} AS marker) "
                if scenario >= 2
                else ""
            )
            where = (
                f" WHERE enabled_{scenario} = {(scenario * 7 + rng.randrange(5)) % 3}"
                if scenario != 1
                else ""
            )
            start = (
                f" START WITH parent_{scenario} IS NULL"
                if scenario in (0, 2)
                else ""
            )
            predicate_terms = [
                f"PRIOR node_{offset} = parent_{offset}"
                for offset in rng.sample(range(11), 4)
            ]
            predicate_terms.extend(
                f"kind_{offset} = PRIOR kind_{offset}"
                for offset in rng.sample(range(11, 23), 3)
            )
            rng.shuffle(predicate_terms)
            sql = (
                f"{prefix}SELECT {', '.join(projections)} "
                f"FROM hierarchy_{scenario}{where}{start} "
                f"CONNECT BY {' AND '.join(predicate_terms)}"
            )

            query = parse_one(sql, dialect="oracle")
            transformed_queries.append(connect_by_to_recursive_cte(query))

        self.assertTrue(all(isinstance(query, exp.Select) for query in transformed_queries))
        self.assertTrue(
            all(query.args.get("with_").args.get("recursive") for query in transformed_queries)
        )
        self.assertFalse(
            any(query.find(exp.ConnectByRoot) for query in transformed_queries)
        )
        self.assertTrue(all(query.find(exp.Union) for query in transformed_queries))
