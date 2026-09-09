import unittest

from lark import Lark
from lark.exceptions import ParseError


class TestCykLoopBehavior(unittest.TestCase):
    def test_generated_terminal_mix(self):
        grammar = r"""
            start: pair
            pair: left right
                | right middle
                | middle left
            left: A | C
            right: B | D
            middle: E | F | G
            A: "a"
            B: "b"
            C: "c"
            D: "d"
            E: "e"
            F: "f"
            G: "g"
        """
        alphabet = "abcdefg"
        symbols = (alphabet[(index * index + 3 * index + 5) % len(alphabet)]
                   for index in range(27))
        text = "".join(symbols)

        parser = Lark(grammar, parser="cyk", start="start")
        with self.assertRaises(ParseError):
            parser.parse(text)
