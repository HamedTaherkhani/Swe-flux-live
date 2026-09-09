import random
import unittest

from lark import Lark


class TestGeneratedDynamicEarleyInput(unittest.TestCase):
    def test_programmatic_mixed_tokens(self):
        rng = random.Random(731)
        letters = "abcdefghijkmnpqrstuvwxyz"
        pieces = []
        for index in range(24):
            if index % 3:
                pieces.append(
                    "".join(letters[rng.randrange(len(letters))] for _ in range(3))
                )
            else:
                pieces.append(
                    "".join(str(rng.randrange(10)) for _ in range(3))
                )

        spacing = [" ", "\t", "  ", " \t"]
        source = ""
        for index, piece in enumerate(pieces):
            if index:
                source += spacing[(index + len(piece)) % len(spacing)]
                source += ";"
                source += spacing[(index * 3) % len(spacing)]
            source += piece

        grammar = r"""
            start: piece (";" piece)*
            piece: WORD | NUMBER
            WORD: /[a-z]{1,3}/
            NUMBER: /[0-9]{1,3}/
            %import common.WS_INLINE
            %ignore WS_INLINE
        """
        parser = Lark(
            grammar,
            parser="earley",
            lexer="dynamic_complete",
            ambiguity="resolve",
        )

        tree = parser.parse(source)
        self.assertEqual(tree.data, "start")
        self.assertEqual(len(tree.children), len(pieces))
