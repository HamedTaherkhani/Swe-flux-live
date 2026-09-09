import random
import unittest

from lark import Token, Tree
from lark.visitors import Transformer_NonRecursive


class NumericFolder(Transformer_NonRecursive):
    def NUM(self, token):
        number = int(token)
        return (number * number + 3 * number + 17) % 10007

    def __default__(self, data, children, meta):
        name_weight = sum((index + 1) * ord(char) for index, char in enumerate(data))
        total = name_weight + len(children) * 97
        for index, child in enumerate(children):
            total = (total * 131 + (index + 5) * child) % 1000003
        return total


class TestNonRecursiveTransformState(unittest.TestCase):
    def test_seeded_variable_width_tree(self):
        rng = random.Random(314159)
        frontier = [
            (
                (index * index * 19 + rng.randrange(1000))
                if index % 6 == 0
                else Token(
                    "NUM",
                    str((rng.randrange(5000) * (index + 11) + index * 23) % 9973),
                )
            )
            for index in range(52)
        ]

        level = 0
        while len(frontier) > 1:
            next_frontier = []
            cursor = 0
            while cursor < len(frontier):
                width = min(2 + rng.randrange(3), len(frontier) - cursor)
                children = frontier[cursor:cursor + width]
                label_code = (sum(ord(str(item)[0]) for item in children) + level * 7) % 5
                next_frontier.append(Tree(f"branch_{level}_{label_code}", children))
                cursor += width
            frontier = next_frontier
            level += 1

        tree = frontier[0]
        transformer = NumericFolder()
        result = Transformer_NonRecursive.transform(transformer, tree)

        self.assertIsInstance(result, int)
        self.assertGreater(level, 2)


if __name__ == "__main__":
    unittest.main()
