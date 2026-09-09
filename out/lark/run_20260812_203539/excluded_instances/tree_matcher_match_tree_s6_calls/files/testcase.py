import random
import unittest

from lark import Lark
from lark.tree_matcher import TreeMatcher


class TestTreeMatcherCallStructure(unittest.TestCase):
    def test_seeded_mixed_segment_batches(self):
        grammar = r"""
            start: segment+
            ?segment: atom | pair | cluster
            atom: WORD
            pair: WORD NUMBER
            cluster: "[" atom ("," atom)+ "]"
            WORD: /[a-z]+/
            NUMBER: /[0-9]+/
            %import common.WS
            %ignore WS
        """
        parser = Lark(grammar, parser="lalr", maybe_placeholders=False)
        matcher = TreeMatcher(parser)
        rng = random.Random(731927)
        sources = []

        for batch in range(18):
            chunks = []
            for offset in range(22 + (batch * 7) % 13):
                choice = rng.randrange(3)
                word = chr(97 + rng.randrange(26)) * (1 + rng.randrange(4))
                if choice == 0:
                    chunks.append(word)
                elif choice == 1:
                    chunks.append(f"{word} {rng.randrange(1000)}")
                else:
                    members = [
                        chr(97 + rng.randrange(26)) * (1 + rng.randrange(3))
                        for _ in range(2 + rng.randrange(4))
                    ]
                    chunks.append("[" + ",".join(members) + "]")
            sources.append(" ".join(chunks))

        matched = []
        for source in sources:
            tree = parser.parse(source)
            result = matcher.match_tree(tree, tree.data)
            self.assertEqual(result.data, tree.data)
            self.assertTrue(result.children)
            matched.append(result)

        self.assertEqual(len(matched), len(sources))
        self.assertGreater(len({len(tree.children) for tree in matched}), 3)
