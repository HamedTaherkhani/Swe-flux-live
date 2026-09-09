import random
import unittest

import click


class TestTruncateVisibleState(unittest.TestCase):
    def styled_word(self, length, salt, density=4):
        rng = random.Random(salt)
        alphabet = "abcdefghijklmnpqrstuvwxyz"
        pieces = []
        for index in range(length):
            if (index + rng.randrange(density)) % density == 0:
                pieces.append(f"\x1b[{31 + rng.randrange(7)}m")
            pieces.append(alphabet[(index * 7 + rng.randrange(len(alphabet))) % len(alphabet)])
            if index % (density + 3) == density:
                pieces.append("\x1b[0m")
        pieces.append("\x1b[0m")
        return "".join(pieces)

    def check_wrap(self, text, width, **kwargs):
        output = click.wrap_text(text, width=width, **kwargs)
        self.assertIsInstance(output, str)
        self.assertGreater(len(output.splitlines()), 1)
        self.assertTrue(any(len(click.unstyle(line)) <= width for line in output.splitlines()))
        self.assertGreater(len(click.unstyle(output)), width)

    def test_alternating_color_runs(self):
        word = self.styled_word(83, 1709, density=2)
        self.check_wrap(word, 17)

    def test_dense_seeded_styles(self):
        word = self.styled_word(109, 8231, density=3)
        self.check_wrap(word, 19)

    def test_generated_plain_word(self):
        rng = random.Random(541)
        letters = [chr(97 + (rng.randrange(26) + index * 5) % 26) for index in range(137)]
        self.check_wrap("".join(letters), 23)

    def test_initial_indent_budget(self):
        prefix = "".join(chr(65 + (index * 11) % 26) for index in range(5))
        word = self.styled_word(91, 3307, density=5)
        self.check_wrap(word, 18, initial_indent=prefix)

    def test_interleaved_short_and_long_words(self):
        long_words = [self.styled_word(44 + index * 9, 700 + index, density=3 + index) for index in range(4)]
        separators = [" ivy ", " ox ", " fern "]
        text = "".join(part for pair in zip(long_words, separators) for part in pair) + long_words[-1]
        self.check_wrap(text, 21)

    def test_narrow_visible_budget(self):
        word = self.styled_word(67, 9949, density=2)
        self.check_wrap(word, 7)

    def test_nested_sgr_sequences(self):
        rng = random.Random(20261)
        pieces = []
        for index in range(96):
            pieces.extend((f"\x1b[{1 + index % 2};{31 + rng.randrange(6)}m", chr(97 + (index * 3) % 26)))
            if index % 11 == 6:
                pieces.append("\x1b[0m")
        self.check_wrap("".join(pieces), 16)

    def test_paragraph_preservation(self):
        first = self.styled_word(74, 481, density=4)
        second = self.styled_word(88, 482, density=6)
        self.check_wrap(first + "\n\n" + second, 20, preserve_paragraphs=True)

    def test_seeded_mixed_tokens(self):
        rng = random.Random(77123)
        tokens = []
        for index in range(18):
            size = rng.randrange(3, 39)
            token = self.styled_word(size, rng.randrange(100000), density=2 + index % 5)
            tokens.append(token)
        self.check_wrap(" ".join(tokens), 14)

    def test_subsequent_indent_budget(self):
        words = [self.styled_word(52 + index * 13, 6110 + index, density=4) for index in range(3)]
        indent = "".join(chr(97 + (index * 9) % 26) for index in range(6))
        self.check_wrap(" seed ".join(words), 22, subsequent_indent=indent)

    def test_tab_expansion_before_wrap(self):
        word = self.styled_word(79, 912, density=5)
        text = "\t".join((word[: len(word) // 3], word[len(word) // 3 :]))
        self.check_wrap(text, 15)

    def test_unicode_visible_characters(self):
        glyphs = "λ界øßЖδ"
        pieces = []
        for index in range(103):
            if index % 5 == 1:
                pieces.append(f"\x1b[{32 + index % 5}m")
            pieces.append(glyphs[(index * 5 + index // 4) % len(glyphs)])
            if index % 9 == 7:
                pieces.append("\x1b[0m")
        self.check_wrap("".join(pieces), 18)
