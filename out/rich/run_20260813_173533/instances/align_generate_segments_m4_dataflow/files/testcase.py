"""Direct exercise of Align.__rich_console__.generate_segments across align paths."""

from __future__ import annotations

import io
import random
import types
import unittest

from rich.align import Align
from rich.console import Console
from rich.constrain import Constrain
from rich.segment import Segment

_GEN_CODE = [
    c
    for c in Align.__rich_console__.__code__.co_consts
    if hasattr(c, "co_name") and c.co_name == "generate_segments"
][0]


def _cell(value: object) -> types.CellType:
    def _holder() -> object:
        return value

    return _holder.__closure__[0]


def _console(width: int = 80, height: int | None = None) -> Console:
    return Console(
        file=io.StringIO(),
        width=width,
        height=height,
        force_terminal=False,
        color_system=None,
        _environ={},
    )


def _build_text(rng: random.Random, slot: int, lines: int) -> str:
    parts: list[str] = []
    for idx in range(lines):
        bucket = (slot * 11 + idx * 7 + rng.randrange(9)) % 5
        if bucket == 0:
            token = "".join(
                chr(ord("a") + (slot + pos) % 26)
                for pos in range(2 + rng.randrange(4))
            )
        elif bucket == 1:
            token = "".join(
                chr(ord("A") + (slot + pos) % 26)
                for pos in range(1 + rng.randrange(5))
            )
        elif bucket == 2:
            token = "·" * (1 + rng.randrange(6))
        elif bucket == 3:
            token = f"#{slot % 97}-{idx % 17}"
        else:
            token = "你" + chr(ord("a") + idx % 26)
        parts.append(token)
    return "\n".join(parts)


def _make_generate_segments(
    align_obj: Align,
    console: Console,
    options,
) -> types.FunctionType:
    align_val = align_obj.align
    width = console.measure(align_obj.renderable, options=options).maximum
    rendered = console.render(
        Constrain(
            align_obj.renderable,
            width if align_obj.width is None else min(width, align_obj.width),
        ),
        options.update(height=None),
    )
    lines = list(Segment.split_lines(rendered))
    width, height = Segment.get_shape(lines)
    lines = Segment.set_shape(lines, width, height)
    new_line = Segment.line()
    excess_space = options.max_width - width
    style = (
        console.get_style(align_obj.style) if align_obj.style is not None else None
    )
    cells = tuple(
        _cell(value)
        for value in (align_val, excess_space, lines, new_line, align_obj, style)
    )
    return types.FunctionType(
        _GEN_CODE,
        Align.__rich_console__.__globals__,
        "generate_segments",
        None,
        cells,
    )


def _drain(generator_fn: types.FunctionType) -> tuple[int, int]:
    segments = list(generator_fn())
    text_len = sum(len(seg.text) for seg in segments)
    checksum = sum(
        (ord(ch) * (idx + 1)) for idx, seg in enumerate(segments) for ch in seg.text
    )
    return len(segments), text_len + (checksum % 997)


def _invoke(
    text: str,
    *,
    align: str = "left",
    style: str | None = None,
    pad: bool = True,
    width: int | None = None,
    console_width: int = 80,
) -> tuple[int, int]:
    console = _console(width=console_width)
    options = console.options
    align_obj = Align(text, align, style=style, pad=pad, width=width)
    generator_fn = _make_generate_segments(align_obj, console, options)
    return _drain(generator_fn)


class TestAlignGenerateSegmentsDataFlow(unittest.TestCase):
    def test_exact_fit_many_lines(self) -> None:
        rng = random.Random(0xB01)
        text = _build_text(rng, 1, 18)
        count, metric = _invoke(text, align="left", width=40, console_width=40)
        self.assertGreater(count, 20)
        self.assertGreater(metric, 0)

    def test_left_pad_programmatic_batch(self) -> None:
        rng = random.Random(0xB02)
        total = 0
        for slot in range(6):
            text = _build_text(rng, slot + 2, 4 + rng.randrange(8))
            count, metric = _invoke(
                text,
                align="left",
                style="bold",
                width=30,
                console_width=50,
            )
            total += count + (metric % 17)
        self.assertGreater(total, 40)

    def test_left_without_pad_flag(self) -> None:
        rng = random.Random(0xB03)
        text = _build_text(rng, 9, 14)
        count, metric = _invoke(text, align="left", pad=False, width=22, console_width=60)
        self.assertGreater(count, 10)
        self.assertNotEqual(metric % 3, 0)

    def test_center_even_excess_with_style(self) -> None:
        rng = random.Random(0xB04)
        text = _build_text(rng, 11, 16)
        count, metric = _invoke(
            text,
            align="center",
            style="italic red",
            width=18,
            console_width=55,
        )
        self.assertGreater(count, 25)
        self.assertGreater(metric, count)

    def test_center_odd_excess_no_pad(self) -> None:
        rng = random.Random(0xB05)
        text = _build_text(rng, 13, 12)
        count, metric = _invoke(
            text,
            align="center",
            pad=False,
            width=15,
            console_width=47,
        )
        self.assertGreater(count, 15)
        self.assertTrue(metric > 0)

    def test_center_single_line_wide(self) -> None:
        rng = random.Random(0xB06)
        text = _build_text(rng, 15, 1)
        count, metric = _invoke(
            text,
            align="center",
            style="underline",
            width=10,
            console_width=72,
        )
        self.assertGreaterEqual(count, 3)
        self.assertGreater(metric, 5)

    def test_right_align_long_run(self) -> None:
        rng = random.Random(0xB07)
        text = _build_text(rng, 17, 20)
        count, metric = _invoke(
            text,
            align="right",
            style="dim",
            width=25,
            console_width=70,
        )
        self.assertGreater(count, 30)
        self.assertGreater(metric, 50)

    def test_right_align_short_lines(self) -> None:
        rng = random.Random(0xB08)
        lines = [chr(ord("z") - (idx % 13)) for idx in range(22)]
        text = "\n".join(lines)
        count, metric = _invoke(text, align="right", width=12, console_width=40)
        self.assertGreater(count, 35)
        self.assertGreater(metric, count)

    def test_exact_fit_zero_excess(self) -> None:
        rng = random.Random(0xB09)
        text = _build_text(rng, 19, 8)
        console = _console(width=24)
        align_obj = Align(text, "left", width=24)
        generator_fn = _make_generate_segments(align_obj, console, console.options)
        count, metric = _drain(generator_fn)
        self.assertGreater(count, 8)
        self.assertGreater(metric, 0)

    def test_left_style_none_path(self) -> None:
        rng = random.Random(0xB0A)
        text = _build_text(rng, 21, 11)
        count, metric = _invoke(text, align="left", style=None, width=20, console_width=44)
        self.assertGreater(count, 12)
        self.assertTrue(metric >= count)

    def test_center_mixed_width_programmatic(self) -> None:
        rng = random.Random(0xB0B)
        metrics: list[int] = []
        for idx in range(7):
            text = _build_text(rng, 23 + idx, 3 + (idx % 6))
            count, metric = _invoke(
                text,
                align="center",
                style="bold green",
                width=14 + (idx % 5),
                console_width=48 + idx,
            )
            metrics.append(count + metric % 23)
        self.assertEqual(len(metrics), 7)
        self.assertGreater(max(metrics), min(metrics))

    def test_right_varying_console_widths(self) -> None:
        rng = random.Random(0xB0C)
        total = 0
        for idx in range(9):
            text = _build_text(rng, 31 + idx, 5 + rng.randrange(7))
            count, metric = _invoke(
                text,
                align="right",
                style="reverse",
                width=16,
                console_width=36 + idx * 3,
            )
            total += count
        self.assertGreater(total, 60)

    def test_left_tight_constraint_exact_branch(self) -> None:
        rng = random.Random(0xB0D)
        text = _build_text(rng, 37, 15)
        count, metric = _invoke(text, align="left", width=len(text.splitlines()[0]), console_width=80)
        self.assertGreater(count, 14)
        self.assertGreater(metric % 97, 0)

    def test_center_heavy_unicode_mix(self) -> None:
        rng = random.Random(0xB0E)
        chunks = ["你", "好", "🎉", "世", "界"]
        body = "".join(chunks[rng.randrange(len(chunks))] for _ in range(24))
        text = "\n".join(body[idx : idx + 6] for idx in range(0, len(body), 6))
        count, metric = _invoke(
            text,
            align="center",
            style="bold",
            width=14,
            console_width=52,
        )
        self.assertGreater(count, 12)
        self.assertGreater(metric, 20)
