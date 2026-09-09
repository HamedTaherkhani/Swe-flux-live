import random
import unittest

from lark import Lark, Token
from lark.parsers.lalr_interactive_parser import InteractiveParser


class TestInteractiveAcceptsCallStructure(unittest.TestCase):
    def test_programmatic_multistage_grammar(self):
        rng = random.Random(8675309)
        stage_count = 18
        rules = []
        terminals = []
        selected = []

        for stage in range(stage_count):
            width = rng.randrange(16, 25)
            names = [f"T_{stage}_{option}" for option in range(width)]
            rules.append(f"stage_{stage}: " + " | ".join(names))
            for option, name in enumerate(names):
                salt = rng.randrange(1000, 10000)
                terminals.append(f'{name}: "word_{stage}_{option}_{salt}"')
            pick = (rng.randrange(width) + stage * stage + len(terminals)) % width
            selected.append((names[pick], f"payload_{stage}_{pick}"))

        grammar = "\n".join(
            [
                "start: " + " ".join(f"stage_{stage}" for stage in range(stage_count)),
                *rules,
                *terminals,
            ]
        )
        parser = Lark(grammar, parser="lalr")
        cursor = parser.parse_interactive("")
        observed_sizes = []

        for token_name, token_value in selected:
            accepted = InteractiveParser.accepts(cursor)
            self.assertIn(token_name, accepted)
            observed_sizes.append(len(accepted))
            cursor.feed_token(Token(token_name, token_value))

        result = cursor.feed_eof()
        self.assertEqual(result.data, "start")
        self.assertGreater(len(set(observed_sizes)), 2)
