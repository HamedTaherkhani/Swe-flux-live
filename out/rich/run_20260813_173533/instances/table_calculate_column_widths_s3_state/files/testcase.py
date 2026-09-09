"""Direct exercise of Table._calculate_column_widths with programmatic inputs."""

from __future__ import annotations

import io
import random
import unittest

from rich.console import Console
from rich.table import Table

_SEED = 0xCA7C0DE


def _column_count(slot: int) -> int:
    rng = random.Random(_SEED ^ (slot * 0x27D4EB2D))
    return 14 + rng.randrange(7)


def _row_count(slot: int) -> int:
    rng = random.Random(_SEED ^ (slot * 0x165667B1))
    return 20 + rng.randrange(17)


def _build_table(column_count: int, row_count: int) -> Table:
    rng = random.Random(_SEED)
    table = Table(
        expand=True,
        box=None,
        show_edge=False,
        padding=(1, 2, 1, 2),
        collapse_padding=False,
        min_width=70 + column_count * 2,
    )
    for col_idx in range(column_count):
        ratio = ((col_idx * 3 + 1) % 4 + 1) if col_idx % 2 == 0 else None
        width = None if ratio else (3 + rng.randrange(7))
        no_wrap = col_idx % 5 == 0
        table.add_column(
            f"Hdr{col_idx}",
            ratio=ratio,
            width=width,
            no_wrap=no_wrap,
        )
    for row_idx in range(row_count):
        cells: list[str] = []
        for col_idx in range(column_count):
            span = 2 + (row_idx * 19 + col_idx * 23 + rng.randrange(31)) % 22
            cells.append("q" * span + chr(ord("a") + (row_idx + col_idx) % 26))
        table.add_row(*cells)
    return table


class TestTableCalculateColumnWidthsState(unittest.TestCase):
    def test_programmatic_width_solver_scenario(self) -> None:
        column_count = _column_count(3)
        row_count = _row_count(5)
        table = _build_table(column_count, row_count)

        console = Console(
            file=io.StringIO(),
            width=70 + column_count * 3,
            height=30,
            color_system=None,
            force_terminal=False,
        )
        options = console.options.update_width(70 + column_count)
        widths = table._calculate_column_widths(console, options)

        self.assertEqual(len(widths), column_count)
        self.assertEqual(sum(widths), options.max_width)
        positive = [value for value in widths if value > 0]
        self.assertGreater(len(positive), column_count // 2)
        self.assertGreater(sum(widths), column_count)
