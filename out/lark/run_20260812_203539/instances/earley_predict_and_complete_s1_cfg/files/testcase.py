import unittest

from lark import Lark


class TestEarleyPredictAndCompleteCFG(unittest.TestCase):
    def test_generated_nested_sequence(self):
        grammar_parts = [
            "start: sequence",
            "sequence: element sequence | element",
            'element: WORD modifier | "(" sequence ")"',
            'modifier: "!" | "?" |',
            "WORD: /[a-z]+/",
            "%import common.WS",
            "%ignore WS",
        ]
        parser = Lark(
            "\n".join(grammar_parts),
            parser="earley",
            ambiguity="explicit",
        )

        words = [
            chr(ord("a") + (index * 7) % 26) * (1 + index % 3)
            for index in range(28)
        ]
        chunks = []
        for index, word in enumerate(words):
            if index % 7 == 3:
                follower = words[(index + 1) % len(words)]
                chunks.append(f"({word} {follower}!)")
            else:
                suffix = "?" if index % 5 == 1 else "!" if index % 5 == 4 else ""
                chunks.append(word + suffix)

        source = " ".join(chunks)
        tree = parser.parse(source)

        self.assertEqual(tree.data, "start")
        self.assertGreater(len(source), len(words))
