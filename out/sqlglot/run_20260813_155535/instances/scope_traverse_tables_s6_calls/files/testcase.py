import random
import unittest

from sqlglot import parse_one
from sqlglot.optimizer.scope import traverse_scope


class TestScopeCallBehavior(unittest.TestCase):
    def test_generated_nested_relations(self):
        rng = random.Random(0x51C0)
        ctes = []

        for index in range(7):
            upstream = f"seed_{rng.randrange(100, 999)}" if index == 0 else f"stage_{index - 1}"
            branches = []
            for branch in range(2 + index % 2):
                left = rng.randrange(1000, 9000)
                right = rng.randrange(1000, 9000)
                branches.append(
                    f"SELECT key, value + {rng.randrange(2, 97)} AS value "
                    f"FROM raw_{left} JOIN lookup_{right} USING (key) "
                    f"WHERE flag = {(index + branch) % 3}"
                )

            derived = " UNION ALL ".join(branches)
            ctes.append(
                f"stage_{index} AS ("
                f"SELECT u.key, d.value FROM {upstream} AS u "
                f"JOIN ({derived}) AS d ON u.key = d.key "
                f"WHERE EXISTS (SELECT 1 FROM guard_{rng.randrange(100, 999)} AS g "
                f"WHERE g.key = u.key)"
                f")"
            )

        query = (
            f"WITH {', '.join(ctes)} "
            "SELECT final.key, final.value "
            f"FROM stage_{len(ctes) - 1} AS final "
            "JOIN (SELECT key FROM audit_left UNION ALL SELECT key FROM audit_right) AS audit "
            "ON final.key = audit.key "
            "WHERE final.value IN (SELECT value FROM allowed_values)"
        )

        scopes = traverse_scope(parse_one(query))

        self.assertGreater(len(scopes), len(ctes))
        self.assertTrue(scopes[-1].is_root)
        self.assertTrue(any(scope.is_cte for scope in scopes))
