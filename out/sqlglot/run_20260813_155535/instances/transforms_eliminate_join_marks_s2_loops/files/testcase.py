import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.transforms import eliminate_join_marks


class TestEliminateJoinMarksLoops(unittest.TestCase):
    def test_seeded_parenthesized_predicates(self):
        label = "join-mark-loop-depths"
        seed = sum((index + 1) * ord(character) for index, character in enumerate(label))
        rng = random.Random(seed)

        predicates = []
        for index in range(37):
            depth = 1 + rng.randrange(5)
            left = f"base.k{(index * 7 + rng.randrange(11)) % 13}"
            right = f"outer_t.v{(index * 5 + rng.randrange(17)) % 19}(+)"
            predicate = f"{left} = {right} + {rng.randrange(23)}"
            predicates.append("(" * depth + predicate + ")" * depth)

        for index in range(13):
            position = rng.randrange(len(predicates) + 1)
            predicates.insert(
                position,
                f"base.flag{(index * 3) % 9} >= {rng.randrange(31)}",
            )

        query = parse_one(
            "SELECT base.id FROM base, outer_t WHERE " + " AND ".join(predicates),
            dialect="oracle",
        )
        transformed = eliminate_join_marks(query)

        self.assertFalse(
            any(column.args.get("join_mark") for column in transformed.find_all(exp.Column))
        )
        self.assertEqual(transformed.args["joins"][0].kind, "LEFT")
        self.assertIsNotNone(transformed.args["joins"][0].args.get("on"))
        self.assertIsNotNone(transformed.args.get("where"))
