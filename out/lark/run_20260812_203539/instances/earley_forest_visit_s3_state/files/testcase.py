import unittest

from lark import Lark


class TestGeneratedEarleyForestState(unittest.TestCase):
    def test_generated_ambiguous_sequence(self):
        rule_names = ("single", "double", "triple")
        alternatives = [
            f"{name}: " + " ".join(["LETTER"] * width)
            for width, name in enumerate(rule_names, start=1)
        ]
        grammar = "\n".join(
            ["start: piece+", "?piece: " + " | ".join(rule_names)]
            + alternatives
            + ["LETTER: /[a-z]/"]
        )
        source = "".join(
            chr(ord("a") + ((index * index * 3 + index * 11 + 7) % 26))
            for index in range(22)
        )

        parser = Lark(
            grammar,
            parser="earley",
            lexer="dynamic_complete",
            ambiguity="resolve",
        )
        tree = parser.parse(source)

        self.assertEqual(tree.data, "start")
        self.assertGreater(len(list(tree.iter_subtrees())), len(source) // 4)


if __name__ == "__main__":
    unittest.main()
