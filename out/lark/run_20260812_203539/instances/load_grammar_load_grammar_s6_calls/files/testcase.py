import random
import unittest

from lark import Lark, Tree


class TestGeneratedGrammarImports(unittest.TestCase):
    def test_seeded_import_and_directive_mix(self):
        rng = random.Random(sum(map(ord, "repo-behave-grammar-imports")))

        imports = [
            ("CNAME", "IDENT"),
            ("INT", "INTEGER"),
            ("WS_INLINE", "GAP"),
            ("ESCAPED_STRING", "QUOTED"),
            ("SIGNED_NUMBER", "SIGNED"),
        ]
        rng.shuffle(imports)

        chain_names = [f"CHAIN_{index:02d}" for index in range(24)]
        terminal_lines = [f'{chain_names[0]}: "{rng.choice("abcdefgh")}0"']
        terminal_lines.extend(
            f'{chain_names[index]}: {chain_names[index - 1]} "{rng.choice("abcdefgh")}"'
            for index in range(1, len(chain_names))
        )
        rng.shuffle(terminal_lines)

        helper_lines = [
            f"helper_{index:02d}: atom {chain_names[(index * index + 3) % len(chain_names)]}?"
            for index in range(18)
        ]
        rng.shuffle(helper_lines)

        extension_targets = chain_names[::2]
        rng.shuffle(extension_targets)

        grammar_lines = [
            *(f"%import common.{source} -> {alias}" for source, alias in imports),
            *terminal_lines,
            "start: sequence",
            "sequence: atom+",
            "atom: IDENT | INTEGER | SIGNED | QUOTED",
            *helper_lines,
            "replaceable: IDENT",
            "%override replaceable: INTEGER | QUOTED",
            *(f"%extend atom: {name}" for name in extension_targets),
            "%declare INDENT_TOKEN DEDENT_TOKEN",
            "%ignore GAP",
            r"%ignore /#[^\n]*/",
        ]
        grammar = "\n".join(grammar_lines)

        parser = Lark(grammar, parser="lalr", start="start")
        words = [
            "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(7))
            for _ in range(19)
        ]
        result = parser.parse(" ".join(words))

        self.assertIsInstance(result, Tree)
        self.assertEqual(result.data, "start")
        self.assertGreater(len(result.children), 0)
