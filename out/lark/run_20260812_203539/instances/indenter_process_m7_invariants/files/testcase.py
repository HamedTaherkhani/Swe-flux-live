import random
import unittest

from lark.indenter import Indenter
from lark.lexer import Token


class ProbeIndenter(Indenter):
    NL_type = "NL"
    OPEN_PAREN_types = ["OPEN"]
    CLOSE_PAREN_types = ["CLOSE"]
    INDENT_type = "INDENT"
    DEDENT_type = "DEDENT"
    tab_len = 4

    def __repr__(self):
        return (
            f"ProbeIndenter(paren_level={self.paren_level},"
            f"indent_level={self.indent_level!r})"
        )


def build_stream(seed, count, flavor, open_count, open_start):
    rng = random.Random(seed * 65537 + flavor * 313)
    open_positions = set()
    if open_count:
        stride = max(2, (count - open_start) // (open_count + 1))
        open_positions = {
            min(count - 1, open_start + offset * stride)
            for offset in range(open_count)
        }

    levels = [0]
    tokens = []
    parentheses_open = False
    for index in range(count):
        if index in open_positions:
            tokens.append(Token("OPEN", f"open_{seed}_{index}"))
            parentheses_open = True
            continue

        if index == 0:
            indent = 1 + (seed + flavor) % 5
            levels.append(indent)
            tokens.append(Token("NL", "\n" + " " * indent))
            continue

        selector = rng.randrange(11)
        if not parentheses_open and selector < 6:
            if selector in (0, 1):
                levels.append(levels[-1] + 1 + rng.randrange(4))
            elif selector == 2 and len(levels) > 2:
                levels = levels[: rng.randrange(2, len(levels))]
            indent = levels[-1]
            if selector == 5 and indent % 4 == 0:
                suffix = "\t" * (indent // 4)
            else:
                suffix = " " * indent
            tokens.append(Token("NL", f"segment_{index}\n{suffix}"))
        elif parentheses_open and selector < 7:
            width = rng.randrange(9)
            suffix = (" " * width) if index % 3 else ("\t" * (width // 4))
            tokens.append(Token("NL", f"ignored_{index}\n{suffix}"))
        else:
            token_type = f"WORD_{(index * 7 + flavor) % 9}"
            tokens.append(Token(token_type, f"value_{seed ^ index}_{flavor}"))
    return tokens


class TestIndenterProcessInvariants(unittest.TestCase):
    def exercise(self, seed, count, flavor, open_count=0, open_start=0):
        indenter = ProbeIndenter()
        stream = build_stream(seed, count, flavor, open_count, open_start)

        produced = list(indenter._process(iter(stream)))

        self.assertTrue(produced)
        self.assertTrue(all(isinstance(token, Token) for token in produced))
        self.assertEqual(indenter.indent_level, [0])
        self.assertGreaterEqual(indenter.paren_level, 0)
        self.assertTrue(any(token.type not in {"INDENT", "DEDENT"} for token in produced))

    def test_balanced_random_walk(self):
        self.exercise(17, 31, 2)

    def test_deep_indentation_ladder(self):
        self.exercise(29, 31 + 7, 7)

    def test_early_open_suppression(self):
        self.exercise(41, 27, 5, 1, 0)

    def test_indented_single_open(self):
        self.exercise(53, 34, 11, 1, 9)

    def test_long_plain_tail(self):
        self.exercise(67, 43, 3)

    def test_midstream_open_suppression(self):
        self.exercise(71, 36, 13, 1, 17)

    def test_narrow_seeded_walk(self):
        self.exercise(83, 29, 17)

    def test_open_after_indentation_burst(self):
        self.exercise(97, 41, 19, 1, 23)

    def test_repeated_newline_pressure(self):
        self.exercise(101, 47, 23)

    def test_shallow_early_open(self):
        self.exercise(113, 33, 29, 1, 4)

    def test_two_unclosed_openers(self):
        self.exercise(127, 39, 31, 2, 1)

    def test_wide_seeded_walk(self):
        self.exercise(139, 45, 37)
