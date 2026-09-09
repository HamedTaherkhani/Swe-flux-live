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
        rng = random.Random(65537)
        grammar = r"""
            start: (WORD | NUMBER | MARK)+
            WORD: /[a-z]+/
            NUMBER: /[0-9]+/
            MARK: /[,:;]/
            %import common.WS
            %ignore WS
        """
        parser = Lark(grammar, parser=None, lexer="basic", postlex=RotatingPostLex())

        alphabet = "abcdefghijklmnopqrstuvwxyz"
        marks = ",:;"
        batches = []
        mode_bits = []
        rolling = rng.randrange(3, 50_000)
        for batch_index in range(95):
            pieces = []
            for item_index in range(38 + (rolling % 13)):
                rolling = (rolling * 73 + rng.randrange(11, 1543) + batch_index * 11 + item_index) % 1_000_003
                selector = rolling % 7
                if selector < 3:
                    width = 2 + rolling % 12
                    pieces.append("".join(alphabet[(rolling // (j + 1) + j * 3) % len(alphabet)] for j in range(width)))
                elif selector < 6:
                    pieces.append(str((rolling * (item_index + 3)) % 999_983))
                else:
                    pieces.append(marks[(rolling + item_index) % len(marks)])
            batches.append(" ".join(pieces))
            mode_bits.append(((rolling >> (batch_index % 5)) ^ batch_index) % 3 != 0)

        token_totals = []
        for text, dont_ignore in zip(batches, mode_bits):
            tokens = list(parser.lex(text, dont_ignore=dont_ignore))
            token_totals.append(len(tokens))
            self.assertTrue(tokens)

        self.assertEqual(len(token_totals), len(batches))
        self.assertGreater(sum(token_totals), len(batches) * 10)