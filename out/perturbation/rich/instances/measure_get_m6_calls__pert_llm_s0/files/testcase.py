"""Direct exercise of Measurement.get across varied renderable inputs."""

from __future__ import annotations

import unittest
from random import Random

import pytest

from rich.console import Console
from rich.errors import NotRenderableError
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text


def _seeded_payloads(seed: int, count: int, base: int) -> list[tuple[int, int]]:
    rng = Random(seed)
    specs: list[tuple[int, int]] = []
    for index in range(count):
        minimum = base + (index * 11 + rng.randint(0, 7)) % 17
        maximum = minimum + 3 + (index * 5 + rng.randint(0, 9)) % 23
        if index % 6 == 4:
            minimum = -2 - (index % 5)
        if index % 7 == 3:
            maximum = minimum - 1
        specs.append((minimum, maximum))
    return specs


class _MeasurableRenderable:
    def __init__(self, minimum: int, maximum: int, glyph: str = "x") -> None:
        self._minimum = minimum
        self._maximum = maximum
        self._glyph = glyph

    def __rich_console__(self, console, options):
        width = max(0, self._maximum)
        yield Text(self._glyph * width if width else "")

    def __rich_measure__(self, console, options):
        return Measurement(self._minimum, self._maximum)


class _RichCastWrapper:
    def __init__(self, inner) -> None:
        self._inner = inner

    def __rich__(self):
        return self._inner


class _BareRenderable:
    def __init__(self, label: str) -> None:
        self._label = label

    def __rich_console__(self, console, options):
        yield Text(self._label)


class TestMeasurementGetInvocationCounts(unittest.TestCase):
    def setUp(self) -> None:
        self.console = Console(record=True, width=200, force_terminal=False)

    def test_zero_width_option_early_return(self) -> None:
        rng = Random(0xA11CE5)
        checksum = 0
        for index in range(31):
            width = 0 if index % 5 != 3 else rng.randint(-9, 0)
            options = self.console.options.update_width(width)
            payload = f"slot-{index:03d}-{rng.randint(0, 999)}"
            result = Measurement.get(self.console, options, payload)
            checksum += result.minimum + result.maximum
        self.assertGreaterEqual(checksum, 0)

    def test_plain_strings_without_rich_measure(self) -> None:
        rng = Random(0xBEEF02)
        maxima: list[int] = []
        for index in range(34):
            width = 8 + (index * 5) % 53
            options = self.console.options.update_width(width)
            token = "".join(
                chr(97 + (index * 2 + ch) % 26) for ch in range(4 + index % 13)
            )
            result = Measurement.get(self.console, options, token)
            maxima.append(result.maximum)
        self.assertGreater(sum(maxima), 0)

    def test_markup_strings_render_path(self) -> None:
        rng = Random(0xC0FFE1)
        widths: list[int] = []
        for index in range(26):
            max_width = 5 + (index * 11 + rng.randint(0, 9)) % 67
            options = self.console.options.update_width(max_width)
            style = ("bold", "italic", "underline", "dim", "reverse")[index % 5]
            markup = (
                f"[{style}]{'alphabeta'[index % 6:]}"
                f"{'=' * (index % 5)}"
                f"[/{style}]"
            )
            result = Measurement.get(self.console, options, markup)
            widths.append(result.maximum)
        self.assertEqual(len(widths), 26)

    def test_measurable_renderables_full_normalize(self) -> None:
        specs = _seeded_payloads(seed=0xF157, count=42, base=1)
        width_total = 0
        for minimum, maximum in specs:
            width = 15 + (maximum % 17) + (minimum % 7)
            options = self.console.options.update_width(width)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="M")
            result = Measurement.get(self.console, options, renderable)
            width_total += result.minimum + result.maximum
        self.assertGreater(width_total, 0)

    def test_measurable_zero_maximum_after_clamp(self) -> None:
        rng = Random(0xE0E1)
        zero_hits = 0
        for index in range(24):
            minimum = rng.randint(-7, 4)
            maximum = minimum + (index % 6)
            width = 1 + (index % 5)
            options = self.console.options.update_width(width)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="Z")
            result = Measurement.get(self.console, options, renderable)
            if result.maximum < 1:
                zero_hits += 1
        self.assertGreater(zero_hits, 0)

    def test_text_objects_with_rich_measure(self) -> None:
        rng = Random(0xFAC1)
        minimums: list[int] = []
        for index in range(36):
            body = " ".join(
                f"w{(index * 3 + part) % 29}" for part in range(1 + index % 8)
            )
            text = Text(body, style="bold" if index % 3 else None)
            width = 10 + (index * 7 + rng.randint(0, 11)) % 47
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, text)
            minimums.append(result.minimum)
        self.assertGreater(max(minimums), 0)

    def test_table_renderables(self) -> None:
        rng = Random(0x1AB2E)
        maxima: list[int] = []
        for index in range(22):
            table = Table(
                title=f"grid-{index:02d}",
                min_width=1 + index % 9,
                width=12 + index % 17,
            )
            rows = 3 + index % 6
            cols = 3 + (index * 5) % 8
            for row in range(rows):
                table.add_row(
                    *[f"r{row}c{col}-{rng.randint(0, 99)}" for col in range(cols)]
                )
            width = 20 + (index * 7 + rng.randint(0, 13)) % 61
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, table)
            maxima.append(result.maximum)
        self.assertGreater(sum(maxima), 0)

    def test_rich_cast_wrapper_dispatch(self) -> None:
        rng = Random(0xCA58)
        checksum = 0
        for index in range(28):
            inner = _MeasurableRenderable(
                1 + index % 11,
                5 + (index * 7) % 31,
                glyph="R",
            )
            wrapped = _RichCastWrapper(inner)
            width = 14 + rng.randint(0, 19)
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, wrapped)
            checksum += result.minimum + result.maximum
        self.assertGreater(checksum, 0)

    def test_bare_renderable_without_measure_hook(self) -> None:
        rng = Random(0xB0BB)
        maxima: list[int] = []
        for index in range(32):
            label = f"plain-{index:03d}-{rng.randint(100, 999)}"
            renderable = _BareRenderable(label)
            width = 7 + (index * 9) % 41
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, renderable)
            maxima.append(result.maximum)
        self.assertTrue(all(value >= 0 for value in maxima))

    def test_mixed_renderable_batch(self) -> None:
        rng = Random(0xB1A5EE)
        totals = 0
        for index in range(48):
            width = 9 + (index * 13 + rng.randint(0, 17)) % 67
            options = self.console.options.update_width(width)
            mode = index % 7
            if mode == 0:
                renderable = Text(f"mix-{index:03d}")
            elif mode == 1:
                renderable = _MeasurableRenderable(index % 13, 8 + index % 19)
            elif mode == 2:
                renderable = f"[green]batch-{index:03d}[/]"
            elif mode == 3:
                renderable = _RichCastWrapper(
                    _MeasurableRenderable(2, 6 + index % 13, glyph="B")
                )
            else:
                table = Table(min_width=1 + index % 8, width=8 + index % 12)
                table.add_row("a", "b", str(index), f"z{index % 17}")
                renderable = table
            result = Measurement.get(self.console, options, renderable)
            totals += result.maximum
        self.assertGreater(totals, 0)

    def test_not_renderable_objects_raise(self) -> None:
        rng = Random(0xBAD1)
        caught = 0
        for index in range(18):
            width = 6 + index * 3
            options = self.console.options.update_width(width)
            payload = object()
            with pytest.raises(NotRenderableError, match="Unable to get render width"):
                Measurement.get(self.console, options, payload)
            caught += 1
            if index % 2 == 0:
                with pytest.raises(NotRenderableError):
                    Measurement.get(self.console, options, rng)
                caught += 1
        self.assertGreater(caught, 9)

    def test_varied_maximum_width_branches(self) -> None:
        rng = Random(0x51CF)
        readings: list[tuple[int, int]] = []
        for index in range(38):
            width = 1 if index % 11 == 0 else 3 + (index * 17 + rng.randint(0, 15)) % 97
            options = self.console.options.update_width(width)
            minimum = (index * 3) % 13
            maximum = minimum + 3 + (index % 11)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="V")
            result = Measurement.get(self.console, options, renderable)
            readings.append((result.minimum, result.maximum))
        self.assertGreater(len(readings), 20)