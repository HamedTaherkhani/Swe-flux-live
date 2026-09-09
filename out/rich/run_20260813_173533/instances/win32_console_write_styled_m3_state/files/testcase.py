"""Direct exercise of LegacyWindowsTerm.write_styled across varied style inputs."""

from __future__ import annotations

import ctypes
import io
import sys
import unittest
from random import Random
from unittest import mock

from rich.color import Color
from rich.style import Style


class _FakeDLL:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, name: str):
        fn = mock.MagicMock(return_value=0)
        setattr(self, name, fn)
        return fn


_platform_patcher = mock.patch.object(sys, "platform", "win32")
_windll_patcher = mock.patch.object(ctypes, "WinDLL", _FakeDLL, create=True)
_platform_patcher.start()
_windll_patcher.start()

if "rich._win32_console" in sys.modules:
    del sys.modules["rich._win32_console"]

import rich._win32_console as _win32_console  # noqa: E402
from rich._win32_console import LegacyWindowsTerm  # noqa: E402

_HANDLE = mock.sentinel.handle
_DEFAULT_ATTR = 7


class _StubScreenBufferInfo:
    dwCursorPosition = type("C", (), {"X": 1, "Y": 2})()
    dwSize = type("C", (), {"X": 80, "Y": 25})()
    wAttributes = _DEFAULT_ATTR


def _make_term() -> LegacyWindowsTerm:
    stream = io.StringIO()
    with mock.patch.object(_win32_console, "GetStdHandle", return_value=_HANDLE):
        with mock.patch.object(
            _win32_console, "GetConsoleScreenBufferInfo", return_value=_StubScreenBufferInfo()
        ):
            with mock.patch.object(_win32_console, "SetConsoleTextAttribute"):
                return LegacyWindowsTerm(stream)


def _write_batch(term: LegacyWindowsTerm, styles: list[Style], texts: list[str]) -> int:
    total = 0
    for index, style in enumerate(styles):
        payload = texts[index % len(texts)]
        term.write_styled(payload, style)
        total += len(payload)
    return total


def _named_color_styles(seed: int, count: int) -> list[Style]:
    rng = Random(seed)
    palette = [
        "black",
        "red",
        "green",
        "yellow",
        "blue",
        "magenta",
        "cyan",
        "white",
        "bright_black",
        "bright_red",
        "bright_green",
        "bright_yellow",
        "bright_blue",
        "bright_magenta",
        "bright_cyan",
        "bright_white",
    ]
    styles: list[Style] = []
    for slot in range(count):
        fg = palette[(slot + rng.randint(0, 3)) % len(palette)]
        bg = palette[(slot * 5 + rng.randint(0, 7)) % len(palette)]
        attrs: list[str] = []
        if slot % 4 == 0:
            attrs.append("bold")
        if slot % 5 == 1:
            attrs.append("dim")
        if slot % 6 == 2:
            attrs.append("reverse")
        prefix = " ".join(attrs)
        spec = f"{prefix} {fg} on {bg}".strip()
        styles.append(Style.parse(spec))
    return styles


def _rgb_styles(seed: int, count: int) -> list[Style]:
    rng = Random(seed)
    styles: list[Style] = []
    for slot in range(count):
        red = rng.randint(0, 255)
        green = rng.randint(0, 255)
        blue = rng.randint(0, 255)
        fg = Color.from_rgb(red, green, blue)
        back_level = (slot * 17 + rng.randint(0, 31)) % 256
        bg = Color.from_ansi(back_level)
        style = Style(color=fg, bgcolor=bg)
        if slot % 3 == 0:
            style = style + Style(bold=True)
        if slot % 4 == 1:
            style = style + Style(dim=True)
        styles.append(style)
    return styles


def _edge_styles(seed: int, count: int) -> list[Style]:
    rng = Random(seed)
    styles: list[Style] = []
    for slot in range(count):
        mode = (slot + rng.randint(0, 2)) % 9
        if mode == 0:
            styles.append(Style.parse("on blue"))
        elif mode == 1:
            styles.append(Style.parse("red"))
        elif mode == 2:
            styles.append(Style())
        elif mode == 3:
            styles.append(Style.parse("bold"))
        elif mode == 4:
            styles.append(Style.parse("dim bright_white on black"))
        elif mode == 5:
            styles.append(Style.parse("reverse cyan on magenta"))
        elif mode == 6:
            styles.append(Style.parse("bold dim green on yellow"))
        elif mode == 7:
            styles.append(Style.parse("underline red on blue"))
        else:
            number = rng.randint(0, 255)
            styles.append(Style(color=Color.from_ansi(number)))
    return styles


def _texts_for(seed: int, count: int) -> list[str]:
    rng = Random(seed)
    return [f"t{index}-{rng.randint(0, 999):03d}" for index in range(count)]


class TestLegacyWindowsWriteStyledState(unittest.TestCase):
    def test_named_palette_batch(self) -> None:
        term = _make_term()
        styles = _named_color_styles(seed=0xA11CE, count=18)
        total = _write_batch(term, styles, _texts_for(0xA11CE, 6))
        self.assertGreater(total, 40)
        self.assertGreater(len(styles), 15)

    def test_rgb_gradient_batch(self) -> None:
        term = _make_term()
        styles = _rgb_styles(seed=0xB22DF, count=17)
        total = _write_batch(term, styles, _texts_for(0xB22DF, 5))
        self.assertGreater(total, 35)
        self.assertEqual(len(styles), 17)

    def test_edge_mode_batch(self) -> None:
        term = _make_term()
        styles = _edge_styles(seed=0xC33E0, count=16)
        total = _write_batch(term, styles, _texts_for(0xC33E0, 4))
        self.assertGreater(total, 20)
        self.assertEqual(len(styles), 16)

    def test_bold_only_sweep(self) -> None:
        term = _make_term()
        rng = Random(0xD44F1)
        styles = [
            Style.parse(f"bold {name}")
            for name in [
                "red",
                "green",
                "blue",
                "yellow",
                "magenta",
                "cyan",
                "white",
                "black",
                "bright_red",
                "bright_blue",
                "bright_green",
                "bright_yellow",
                "bright_magenta",
                "bright_cyan",
                "bright_white",
                "bright_black",
            ]
        ]
        rng.shuffle(styles)
        total = _write_batch(term, styles, _texts_for(0xD44F1, 3))
        self.assertGreater(total, 25)

    def test_dim_bright_sweep(self) -> None:
        term = _make_term()
        styles = [
            Style.parse(f"dim {name}")
            for name in [
                "bright_red",
                "bright_green",
                "bright_blue",
                "bright_yellow",
                "bright_magenta",
                "bright_cyan",
                "bright_white",
                "bright_black",
                "red",
                "green",
                "blue",
                "yellow",
                "magenta",
                "cyan",
                "white",
                "black",
            ]
        ]
        total = _write_batch(term, styles, _texts_for(0xE55A2, 3))
        self.assertGreater(total, 20)

    def test_reverse_sweep(self) -> None:
        term = _make_term()
        pairs = [
            ("red", "blue"),
            ("green", "magenta"),
            ("yellow", "cyan"),
            ("blue", "red"),
            ("magenta", "green"),
            ("cyan", "yellow"),
            ("white", "black"),
            ("black", "white"),
            ("bright_red", "bright_blue"),
            ("bright_green", "bright_yellow"),
            ("bright_magenta", "bright_cyan"),
            ("bright_white", "bright_black"),
            ("red", "green"),
            ("blue", "yellow"),
            ("magenta", "cyan"),
            ("white", "red"),
        ]
        styles = [Style.parse(f"reverse {fg} on {bg}") for fg, bg in pairs]
        total = _write_batch(term, styles, _texts_for(0xF66B3, 2))
        self.assertGreater(total, 15)

    def test_background_only_sweep(self) -> None:
        term = _make_term()
        colors = [
            "red",
            "green",
            "blue",
            "yellow",
            "magenta",
            "cyan",
            "white",
            "black",
            "bright_red",
            "bright_green",
            "bright_blue",
            "bright_yellow",
            "bright_magenta",
            "bright_cyan",
            "bright_white",
            "bright_black",
        ]
        styles = [Style.parse(f"on {name}") for name in colors]
        total = _write_batch(term, styles, _texts_for(0x177C4, 2))
        self.assertGreater(total, 10)

    def test_foreground_only_sweep(self) -> None:
        term = _make_term()
        colors = [
            "red",
            "green",
            "blue",
            "yellow",
            "magenta",
            "cyan",
            "white",
            "black",
            "bright_red",
            "bright_green",
            "bright_blue",
            "bright_yellow",
            "bright_magenta",
            "bright_cyan",
            "bright_white",
            "bright_black",
        ]
        styles = [Style.parse(name) for name in colors]
        total = _write_batch(term, styles, _texts_for(0x288D5, 2))
        self.assertGreater(total, 10)

    def test_mixed_attribute_batch(self) -> None:
        term = _make_term()
        rng = Random(0x399E6)
        styles: list[Style] = []
        for slot in range(18):
            fg = Color.from_ansi(rng.randint(0, 255))
            bg = Color.from_ansi(rng.randint(0, 255))
            style = Style(color=fg, bgcolor=bg)
            if slot % 2 == 0:
                style = style + Style(bold=True)
            if slot % 3 == 0:
                style = style + Style(dim=True)
            if slot % 5 == 1:
                style = style + Style(reverse=True)
            styles.append(style)
        total = _write_batch(term, styles, _texts_for(0x399E6, 4))
        self.assertGreater(total, 30)

    def test_default_and_bold_dim(self) -> None:
        term = _make_term()
        styles = [Style()]
        for slot in range(15):
            if slot % 3 == 0:
                styles.append(Style.parse("bold red on blue"))
            elif slot % 3 == 1:
                styles.append(Style.parse("dim bright_white on black"))
            else:
                styles.append(Style.parse("reverse green on yellow"))
        total = _write_batch(term, styles, _texts_for(0x4AAF7, 3))
        self.assertGreater(total, 20)

    def test_ansi_number_sweep(self) -> None:
        term = _make_term()
        rng = Random(0x5BB08)
        styles = []
        for slot in range(17):
            fg_num = (slot * 13 + rng.randint(0, 11)) % 256
            bg_num = (slot * 29 + rng.randint(0, 17)) % 256
            styles.append(
                Style(
                    color=Color.from_ansi(fg_num),
                    bgcolor=Color.from_ansi(bg_num),
                )
            )
        total = _write_batch(term, styles, _texts_for(0x5BB08, 3))
        self.assertGreater(total, 25)

    def test_combined_seed_batches(self) -> None:
        term = _make_term()
        styles: list[Style] = []
        for batch_seed in (0x6CC19, 0x7DD2A, 0x8EE3B):
            styles.extend(_named_color_styles(batch_seed, 6))
            styles.extend(_edge_styles(batch_seed + 1, 4))
        total = _write_batch(term, styles, _texts_for(0x9FF4C, 5))
        self.assertGreater(len(styles), 25)
        self.assertGreater(total, 50)
