import io
import random
import unittest

from rich.console import Console
from rich.syntax import Syntax


def _build_python_module(seed: int, statement_count: int) -> str:
    rng = random.Random(seed)
    keywords = ("if", "elif", "else", "for", "while", "def", "return", "pass")
    rows: list[str] = []
    for index in range(statement_count):
        depth = index % 4
        indent = "    " * depth
        pick = index % 7
        if pick == 0:
            rows.append(f"{indent}def worker_{index}(value):")
        elif pick == 1:
            rows.append(f"{indent}    total = value + {rng.randint(1, 40)}")
        elif pick == 2:
            rows.append(f"{indent}    if total > {rng.randint(5, 25)}:")
        elif pick == 3:
            rows.append(f"{indent}        return total * {rng.randint(2, 6)}")
        elif pick == 4:
            rows.append(f"{indent}    for item in range({rng.randint(2, 5)}):")
        elif pick == 5:
            rows.append(f"{indent}        acc = item + {rng.randint(1, 9)}")
        else:
            token = rng.choice(keywords)
            rows.append(f"{indent}# marker {token} {index}")
    return "\n".join(rows) + "\n"


class TestSyntaxGetSyntaxDataFlow(unittest.TestCase):
    def test_get_syntax_line_number_wrap_slice(self) -> None:
        source = _build_python_module(seed=17, statement_count=28)
        highlight = {row for row in range(4, 24, 5)}
        syntax = Syntax(
            source,
            "python",
            line_numbers=True,
            word_wrap=True,
            line_range=(4, 22),
            highlight_lines=highlight,
            indent_guides=True,
            padding=(1, 2, 1, 1),
            tab_size=4,
            start_line=4,
        )
        console = Console(
            width=52,
            force_terminal=True,
            legacy_windows=False,
            file=io.StringIO(),
        )
        options = console.options
        segments = list(syntax._get_syntax(console, options))

        self.assertGreater(len(segments), 120)
        self.assertGreater(sum(len(segment.text) for segment in segments), 400)
        self.assertTrue(any("\n" in segment.text for segment in segments))
