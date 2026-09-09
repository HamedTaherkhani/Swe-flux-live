"""Indirect exercise of console buffer flushing via update_screen_lines."""

import io
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.segment import Segment


def _build_screen_lines(seed: int, count: int) -> list:
    """Build many rendered screen lines with deterministic varied widths."""
    rng = __import__("random").Random(seed)
    base = 340 + (count % 5) + (seed % 9)
    lines = []
    for index in range(count):
        width = base + (index % 7) * 11 + (index * 3) % 5 + rng.randint(0, 2)
        label = f"R{index:02d}-"
        padding = max(1, width - len(label))
        payload = label + ("@" * padding)
        lines.append([Segment(payload + "\n")])
    return lines


class TestConsoleWriteBufferState(unittest.TestCase):
    def test_update_screen_lines_batch_write(self) -> None:
        output = io.StringIO()
        console = Console(
            file=output,
            force_terminal=True,
            width=120,
            height=40,
            legacy_windows=False,
        )
        screen_lines = _build_screen_lines(seed=0xC0FFEE, count=30)

        with patch("rich.console.WINDOWS", True):
            with console.screen():
                console.update_screen_lines(screen_lines)

        rendered = output.getvalue()
        self.assertGreater(len(rendered), 8000)
        self.assertEqual(rendered.count("\n"), 30)
        self.assertIn("R00-", rendered)
        self.assertIn("R29-", rendered)
        self.assertGreater(rendered.find("R20-"), 0)
