import random
import unittest

from lark import Lark
from lark.lark import PostLex


class RotatingPostLex(PostLex):
    def process(self, stream):
        for token in stream:
            yield token


class TestLarkLexCallFlow(unittest.TestCase):
    def test_programmatic_lexing_modes(self):
        rng = random.Random(90210)
        grammar = r"""
            start: (WORD | NUMBER | MARK)+
            WORD: /[a-z]+/
            NUMBER: /[0-9]+/
            MARK: /[,:;]/
            %import common.WS
            %ignore WS
        """
        parser = Lark(grammar, parser=None, lexer="basic", postlex=RotatingPostLex())

        alphabet = "abcdefghijklm"
        marks = ",:;"
        batches = []
        mode_bits = []
        rolling = rng.randrange(1, 10_000)
        for batch_index in range(27):
            pieces = []
            for item_index in range(18 + (rolling % 7)):
                rolling = (rolling * 73 + rng.randrange(19, 997) + batch_index * 11 + item_index) % 104_729
                selector = rolling % 5
                if selector < 2:
                    width = 2 + rolling % 8
                    pieces.append("".join(alphabet[(rolling // (j + 1) + j * 3) % len(alphabet)] for j in range(width)))
                elif selector < 4:
                    pieces.append(str((rolling * (item_index + 3)) % 100_003))
                else:
                    pieces.append(marks[(rolling + item_index) % len(marks)])
            batches.append(" ".join(pieces))
            mode_bits.append(((rolling >> (batch_index % 9)) ^ batch_index) % 4 != 0)

        token_totals = []
        for text, dont_ignore in zip(batches, mode_bits):
            tokens = list(parser.lex(text, dont_ignore=dont_ignore))
            token_totals.append(len(tokens))
            self.assertTrue(tokens)

        self.assertEqual(len(token_totals), len(batches))
        self.assertGreater(sum(token_totals), len(batches) * 10)
