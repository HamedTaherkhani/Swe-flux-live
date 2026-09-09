import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lark.tools import standalone


class TestStandaloneCommand(unittest.TestCase):
    def test_seeded_compressed_generation(self):
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate("repo-behave-standalone")))
        terminal_names = [f"TOKEN_{index:02d}" for index in range(36)]
        terminal_lines = [
            f'{name}: "tok_{index:02d}_{rng.choice("abcdefghijklm")}"'
            for index, name in enumerate(terminal_names)
        ]
        rng.shuffle(terminal_lines)
        rng.shuffle(terminal_names)
        grammar = "\n".join(
            [
                "start: item+",
                "item: " + " | ".join(terminal_names),
                *terminal_lines,
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            grammar_path = Path(temp_dir) / "generated.lark"
            output_path = Path(temp_dir) / "generated_parser.py"
            grammar_path.write_text(grammar, encoding="utf-8")

            argv = [
                "standalone",
                "--compress",
                "--out",
                str(output_path),
                str(grammar_path),
            ]
            with mock.patch.object(sys, "argv", argv):
                standalone.main()

            generated = output_path.read_text(encoding="utf-8")
            self.assertGreater(len(generated), len(grammar) * len(terminal_names))
            self.assertTrue(generated.startswith("# The file was automatically generated"))
            self.assertIn("def Lark_StandAlone(**kwargs):", generated)

