import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lark import Tree
from lark import parser_frontends


class TestCreateEarleyParserDataFlow(unittest.TestCase):
    def _exercise(self, seed, size, stride):
        rng = random.Random(seed)
        lexer_types = ("dynamic", "dynamic_complete", "basic", "contextual")
        ambiguities = ("resolve", "forest", "explicit")
        calls = []

        def make_parser(kind):
            def factory(lexer_conf, parser_conf, **kwargs):
                record = (kind, lexer_conf.lexer_type, parser_conf.marker, kwargs)
                calls.append(record)
                return record

            return factory

        dynamic_factory = make_parser("dynamic-factory")
        basic_factory = make_parser("basic-factory")
        with patch.object(parser_frontends, "create_earley_parser__dynamic", dynamic_factory), \
                patch.object(parser_frontends, "create_earley_parser__basic", basic_factory):
            for index in range(size):
                mixed = rng.randrange(size * stride + seed) + index * stride
                lexer_type = lexer_types[(mixed + index + stride) % len(lexer_types)]
                ambiguity = ambiguities[(mixed // stride + index) % len(ambiguities)]
                chosen_tree_class = (None, Tree, tuple, dict)[
                    (mixed ^ seed ^ index) % 4
                ]
                options = SimpleNamespace(
                    ambiguity=ambiguity,
                    debug=bool((mixed + rng.randrange(7)) % 3),
                    tree_class=chosen_tree_class,
                    ordered_sets=bool((mixed // 2 + index) % 2),
                )
                lexer_conf = SimpleNamespace(lexer_type=lexer_type)
                parser_conf = SimpleNamespace(marker=(seed * (index + 1) + mixed) % 997)
                result = parser_frontends.create_earley_parser(
                    lexer_conf, parser_conf, options
                )
                self.assertIs(result, calls[-1])

        self.assertEqual(len(calls), size)
        self.assertTrue(all(call[-1] for call in calls))

    def test_seeded_prime_stride(self):
        self._exercise(103, 17, 3)

    def test_seeded_even_stride(self):
        self._exercise(211, 18, 4)

    def test_seeded_square_stride(self):
        self._exercise(307, 19, 5)

    def test_seeded_wide_stride(self):
        self._exercise(401, 20, 7)

    def test_seeded_dense_stride(self):
        self._exercise(503, 21, 2)

    def test_seeded_large_stride(self):
        self._exercise(601, 22, 11)

    def test_seeded_offset_stride(self):
        self._exercise(709, 23, 6)

    def test_seeded_odd_stride(self):
        self._exercise(809, 24, 9)

    def test_seeded_tall_stride(self):
        self._exercise(907, 25, 13)

    def test_seeded_short_stride(self):
        self._exercise(1009, 26, 8)

    def test_seeded_coprime_stride(self):
        self._exercise(1103, 27, 10)

    def test_seeded_final_stride(self):
        self._exercise(1201, 28, 12)
