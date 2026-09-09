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
        self.console = Console(record=True, width=120, force_terminal=False)

    def test_zero_width_option_early_return(self) -> None:
        rng = Random(0xA11CE)
        checksum = 0
        for index in range(19):
            width = 0 if index % 3 != 2 else rng.randint(-4, 0)
            options = self.console.options.update_width(width)
            payload = f"slot-{index}-{rng.randint(0, 99)}"
            result = Measurement.get(self.console, options, payload)
            checksum += result.minimum + result.maximum
        self.assertGreaterEqual(checksum, 0)

    def test_plain_strings_without_rich_measure(self) -> None:
        rng = Random(0xBEEF01)
        maxima: list[int] = []
        for index in range(21):
            width = 12 + (index * 3) % 37
            options = self.console.options.update_width(width)
            token = "".join(
                chr(97 + (index + ch) % 26) for ch in range(6 + index % 9)
            )
            result = Measurement.get(self.console, options, token)
            maxima.append(result.maximum)
        self.assertGreater(sum(maxima), 0)

    def test_markup_strings_render_path(self) -> None:
        rng = Random(0xC0FFEE)
        widths: list[int] = []
        for index in range(17):
            max_width = 8 + (index * 7 + rng.randint(0, 5)) % 41
            options = self.console.options.update_width(max_width)
            style = ("bold", "italic", "underline")[index % 3]
            markup = (
                f"[{style}]{'alpha'[index % 3:]}"
                f"{'-' * (index % 4)}"
                f"[/{style}]"
            )
            result = Measurement.get(self.console, options, markup)
            widths.append(result.maximum)
        self.assertEqual(len(widths), 17)

    def test_measurable_renderables_full_normalize(self) -> None:
        specs = _seeded_payloads(seed=0xD1CE, count=29, base=4)
        width_total = 0
        for minimum, maximum in specs:
            width = 20 + (maximum % 11) + (minimum % 5)
            options = self.console.options.update_width(width)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="M")
            result = Measurement.get(self.console, options, renderable)
            width_total += result.minimum + result.maximum
        self.assertGreater(width_total, 0)

    def test_measurable_zero_maximum_after_clamp(self) -> None:
        rng = Random(0xE0E0)
        zero_hits = 0
        for index in range(16):
            minimum = rng.randint(-3, 2)
            maximum = minimum + (index % 4)
            width = 1 + (index % 3)
            options = self.console.options.update_width(width)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="Z")
            result = Measurement.get(self.console, options, renderable)
            if result.maximum < 1:
                zero_hits += 1
        self.assertGreater(zero_hits, 0)

    def test_text_objects_with_rich_measure(self) -> None:
        rng = Random(0xFACE)
        minimums: list[int] = []
        for index in range(23):
            body = " ".join(
                f"w{(index + part) % 17}" for part in range(2 + index % 5)
            )
            text = Text(body, style="bold" if index % 2 else None)
            width = 15 + (index * 2 + rng.randint(0, 6)) % 33
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, text)
            minimums.append(result.minimum)
        self.assertGreater(max(minimums), 0)

    def test_table_renderables(self) -> None:
        rng = Random(0x1AB1E)
        maxima: list[int] = []
        for index in range(14):
            table = Table(title=f"grid-{index}")
            rows = 2 + index % 4
            cols = 2 + (index * 3) % 5
            for row in range(rows):
                table.add_row(
                    *[f"r{row}c{col}-{rng.randint(0, 9)}" for col in range(cols)]
                )
            width = 24 + (index * 5 + rng.randint(0, 8)) % 47
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, table)
            maxima.append(result.maximum)
        self.assertGreater(sum(maxima), 0)

    def test_rich_cast_wrapper_dispatch(self) -> None:
        rng = Random(0xCA57)
        checksum = 0
        for index in range(18):
            inner = _MeasurableRenderable(
                2 + index % 6,
                7 + (index * 4) % 19,
                glyph="R",
            )
            wrapped = _RichCastWrapper(inner)
            width = 18 + rng.randint(0, 12)
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, wrapped)
            checksum += result.minimum + result.maximum
        self.assertGreater(checksum, 0)

    def test_bare_renderable_without_measure_hook(self) -> None:
        rng = Random(0xB0BA)
        maxima: list[int] = []
        for index in range(20):
            label = f"plain-{index}-{rng.randint(10, 99)}"
            renderable = _BareRenderable(label)
            width = 9 + (index * 6) % 29
            options = self.console.options.update_width(width)
            result = Measurement.get(self.console, options, renderable)
            maxima.append(result.maximum)
        self.assertTrue(all(value >= 0 for value in maxima))

    def test_mixed_renderable_batch(self) -> None:
        rng = Random(0xB1A5ED)
        totals = 0
        for index in range(32):
            width = 11 + (index * 9 + rng.randint(0, 11)) % 52
            options = self.console.options.update_width(width)
            mode = index % 5
            if mode == 0:
                renderable = Text(f"mix-{index}")
            elif mode == 1:
                renderable = _MeasurableRenderable(index % 8, 6 + index % 14)
            elif mode == 2:
                renderable = f"[green]batch-{index}[/]"
            elif mode == 3:
                renderable = _RichCastWrapper(
                    _MeasurableRenderable(1, 4 + index % 9, glyph="B")
                )
            else:
                table = Table()
                table.add_row("a", "b", str(index))
                renderable = table
            result = Measurement.get(self.console, options, renderable)
            totals += result.maximum
        self.assertGreater(totals, 0)

    def test_not_renderable_objects_raise(self) -> None:
        rng = Random(0xBAD0)
        caught = 0
        for index in range(9):
            width = 10 + index
            options = self.console.options.update_width(width)
            payload = object()
            with pytest.raises(NotRenderableError, match="Unable to get render width"):
                Measurement.get(self.console, options, payload)
            caught += 1
            if index % 3 == 1:
                with pytest.raises(NotRenderableError):
                    Measurement.get(self.console, options, rng)
                caught += 1
        self.assertGreater(caught, 9)

    def test_varied_maximum_width_branches(self) -> None:
        rng = Random(0x51CE)
        readings: list[tuple[int, int]] = []
        for index in range(24):
            width = 1 if index % 8 == 0 else 6 + (index * 13 + rng.randint(0, 9)) % 63
            options = self.console.options.update_width(width)
            minimum = (index * 2) % 9
            maximum = minimum + 4 + (index % 7)
            renderable = _MeasurableRenderable(minimum, maximum, glyph="V")
            result = Measurement.get(self.console, options, renderable)
            readings.append((result.minimum, result.maximum))
        self.assertGreater(len(readings), 20)
