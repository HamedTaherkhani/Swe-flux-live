"""Exercise Syntax rendering through console entry points."""

from __future__ import annotations

import io
import random
import unittest
from typing import Optional

from rich.console import Console
from rich.syntax import Syntax


def _capture_console(
    *,
    width: int = 100,
    height: int = 40,
    force_terminal: Optional[bool] = True,
) -> Console:
    return Console(
        width=width,
        height=height,
        force_terminal=force_terminal,
        legacy_windows=False,
        color_system="truecolor",
        _environ={},
    )


def _line_count(seed: int, slot: int) -> int:
    rng = random.Random(seed ^ (slot * 0x85EBCA6B))
    return 20 + rng.randrange(20)


def _build_pythonish(rng: random.Random, lines: int, prefix: str) -> str:
    body: list[str] = []
    for idx in range(lines):
        token = (idx * 37 + rng.randrange(211)) % 997
        if idx % 5 == 0:
            body.append(f"{prefix}def worker_{idx}(value={token}):")
            body.append(f"{prefix}    return value + {rng.randrange(9)}")
        elif idx % 7 == 0:
            body.append(f"{prefix}for item in range({1 + token % 6}):")
            body.append(f"{prefix}    total += item * {rng.randrange(5)}")
        else:
            body.append(f"{prefix}total = {token}  # slot marker")
    return "\n".join(body) + "\n"


def _build_jsonish(rng: random.Random, entries: int) -> str:
    parts = ["{"]
    for idx in range(entries):
        key = f"k{idx}"
        value = (idx * 13 + rng.randrange(97)) % 500
        comma = "," if idx + 1 < entries else ""
        parts.append(f'  "{key}": {value}{comma}')
    parts.append("}")
    return "\n".join(parts) + "\n"


def _render_panel(
    console: Console,
    *,
    code: str,
    lexer: str,
    theme: str = "monokai",
    dedent: bool = False,
    line_numbers: bool = False,
    start_line: int = 1,
    line_range: Optional[tuple[Optional[int], Optional[int]]] = None,
    word_wrap: bool = False,
    background_color: Optional[str] = None,
    indent_guides: bool = False,
    code_width: Optional[int] = None,
    tab_size: int = 4,
    highlight_lines: Optional[set[int]] = None,
    stylize: bool = False,
) -> str:
    panel = Syntax(
        code,
        lexer,
        theme=theme,
        dedent=dedent,
        line_numbers=line_numbers,
        start_line=start_line,
        line_range=line_range,
        word_wrap=word_wrap,
        background_color=background_color,
        indent_guides=indent_guides,
        code_width=code_width,
        tab_size=tab_size,
        highlight_lines=highlight_lines,
    )
    if stylize:
        panel.stylize_range("bold red", (2, 0), (3, 4))
        panel.stylize_range("italic", (5, 2), (7, 1), style_before=True)
    console.begin_capture()
    console.print(panel)
    return console.end_capture()


class TestSyntaxHighlightInvocationCounts(unittest.TestCase):
    def _assert_nonempty_capture(self, captured: str, min_len: int) -> None:
        self.assertGreater(len(captured), min_len)
        self.assertTrue(captured.strip() or "\x1b" in captured)

    def test_basic_python_panel(self) -> None:
        console = _capture_console(width=90)
        rng = random.Random(0xA11)
        captured = _render_panel(
            console,
            code=_build_pythonish(rng, _line_count(0xA11, 1), ""),
            lexer="python",
        )
        self._assert_nonempty_capture(captured, 50)

    def test_json_theme_emacs(self) -> None:
        console = _capture_console(width=70)
        rng = random.Random(0xB12)
        captured = _render_panel(
            console,
            code=_build_jsonish(rng, _line_count(0xB12, 2)),
            lexer="json",
            theme="emacs",
        )
        self.assertIn("k0", captured)

    def test_invalid_lexer_uses_default(self) -> None:
        console = _capture_console()
        rng = random.Random(0xC13)
        captured = _render_panel(
            console,
            code=_build_pythonish(rng, _line_count(0xC13, 3), "    "),
            lexer="not-a-real-lexer-alias-xyz",
            dedent=True,
        )
        self._assert_nonempty_capture(captured, 40)

    def test_constructor_line_range_window(self) -> None:
        console = _capture_console(width=80)
        rng = random.Random(0xD14)
        code = _build_pythonish(rng, _line_count(0xD14, 4), "")
        panel = Syntax(
            code,
            "python",
            line_range=(4, 11),
            line_numbers=True,
            background_color="grey11",
        )
        console.begin_capture()
        console.print(panel)
        captured = console.end_capture()
        self.assertGreater(captured.count("\n"), 6)

    def test_stylized_ranges_overlay(self) -> None:
        console = _capture_console()
        rng = random.Random(0xE15)
        captured = _render_panel(
            console,
            code=_build_pythonish(rng, _line_count(0xE15, 5), ""),
            lexer="python",
            stylize=True,
            background_color="default",
        )
        self._assert_nonempty_capture(captured, 60)

    def test_word_wrap_with_numbers(self) -> None:
        console = _capture_console(width=36, height=20)
        rng = random.Random(0xF66)
        long_lines = []
        for idx in range(_line_count(0xF66, 6)):
            long_lines.append("x" * (24 + (idx % 9)) + f" = {rng.randrange(999)}")
        captured = _render_panel(
            console,
            code="\n".join(long_lines) + "\n",
            lexer="python",
            line_numbers=True,
            word_wrap=True,
            start_line=10,
        )
        self.assertGreater(len(captured), 80)

    def test_dedent_tabs_and_guides(self) -> None:
        console = _capture_console(width=88)
        rng = random.Random(0xA77)
        tabbed = []
        for idx in range(_line_count(0xA77, 7)):
            depth = idx % 4
            tabbed.append("\t" * depth + f"node_{idx} = {rng.randrange(256)}")
        captured = _render_panel(
            console,
            code="\n".join(tabbed) + "\n",
            lexer="python",
            dedent=True,
            indent_guides=True,
            tab_size=2,
        )
        self.assertIn("node_", captured)

    def test_rust_lexer_narrow_width(self) -> None:
        console = _capture_console(width=48)
        rng = random.Random(0xB88)
        lines = []
        for idx in range(_line_count(0xB88, 8)):
            lines.append(f"fn probe_{idx}() -> u32 {{ {rng.randrange(4096)} }}")
        captured = _render_panel(
            console,
            code="\n".join(lines) + "\n",
            lexer="rust",
            code_width=30,
            line_numbers=True,
            highlight_lines={3, 7, 12},
        )
        self._assert_nonempty_capture(captured, 70)

    def test_sequential_multi_lexer_batch(self) -> None:
        console = _capture_console(width=96)
        combined = io.StringIO()
        lexers = ("python", "json", "yaml", "sql", "bash")
        for slot, lexer_name in enumerate(lexers):
            rng = random.Random(0x319 + slot * 131)
            if lexer_name == "json":
                payload = _build_jsonish(rng, _line_count(0x319, slot + 9))
            else:
                payload = _build_pythonish(rng, _line_count(0x319, slot + 9), "")
            chunk = _render_panel(
                console,
                code=payload,
                lexer=lexer_name,
                line_numbers=slot % 2 == 0,
                background_color="grey15" if slot % 3 == 0 else None,
            )
            combined.write(chunk)
        merged = combined.getvalue()
        self.assertGreater(len(merged), 120)

    def test_measure_before_render(self) -> None:
        console = _capture_console(width=64)
        rng = random.Random(0x41A)
        panel = Syntax(
            _build_pythonish(rng, _line_count(0x41A, 10), ""),
            "python",
            line_numbers=True,
        )
        measurement = console.measure(panel)
        self.assertGreater(measurement.maximum, measurement.minimum)
        console.begin_capture()
        console.print(panel)
        captured = console.end_capture()
        self._assert_nonempty_capture(captured, 45)

    def test_open_ended_line_range_tail(self) -> None:
        console = _capture_console()
        rng = random.Random(0xC99)
        panel = Syntax(
            _build_pythonish(rng, _line_count(0xC99, 11), ""),
            "python",
            line_range=(None, 6),
            word_wrap=False,
        )
        console.begin_capture()
        console.print(panel)
        captured = console.end_capture()
        self.assertGreater(captured.count("total"), 2)

    def test_yaml_with_transparent_background(self) -> None:
        console = _capture_console(force_terminal=False, width=72)
        rng = random.Random(0x61C)
        rows = []
        for idx in range(_line_count(0x61C, 12)):
            rows.append(f"field_{idx}: {rng.randrange(800)}")
        captured = _render_panel(
            console,
            code="\n".join(rows) + "\n",
            lexer="yaml",
            theme="native",
            indent_guides=True,
        )
        self.assertGreater(captured.count("field_"), 4)

    def test_nested_range_and_stylize_stack(self) -> None:
        console = _capture_console(width=84, height=30)
        rng = random.Random(0x71D)
        code = _build_pythonish(rng, _line_count(0x71D, 13), "")
        panel = Syntax(
            code,
            "python",
            line_range=(2, 13),
            line_numbers=True,
            background_color="blue",
            word_wrap=True,
        )
        panel.stylize_range("underline", (1, 0), (2, 8))
        panel.stylize_range("reverse", (9, 1), (14, 0))
        console.begin_capture()
        console.print(panel)
        captured = console.end_capture()
        self._assert_nonempty_capture(captured, 90)
