"""Exercise generate_lorem_ipsum while-loop iteration dynamics."""

from __future__ import annotations

import random
import unittest

from jinja2.utils import generate_lorem_ipsum


class TestGenerateLoremIpsumLoops(unittest.TestCase):
    """Drive generate_lorem_ipsum word-selection while-loop iterations."""

    def test_while_loop_word_selection(self) -> None:
        seed_material = sum(
            ord(ch) * (pos + 1) for pos, ch in enumerate("lorem_ipsum_trace")
        )
        random.seed(seed_material)

        base = sum(ord(ch) for ch in "lorem_ipsum_trace")
        paragraph_count = (base % 7) + 4
        min_words = (base % 15) + 25
        max_words = min_words + (base % 20) + 30

        result = generate_lorem_ipsum(
            n=paragraph_count,
            html=False,
            min=min_words,
            max=max_words,
        )

        self.assertIsInstance(result, str)
        self.assertGreater(len(result), paragraph_count * min_words)
        self.assertEqual(result.count("\n\n"), paragraph_count - 1)
        self.assertTrue(result.endswith("."))
