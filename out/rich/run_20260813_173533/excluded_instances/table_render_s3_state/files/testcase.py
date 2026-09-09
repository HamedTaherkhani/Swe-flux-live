"""Deterministic exercise of Table._render for S3_ProgramState instance."""

import unittest

from rich.console import Console
from rich.table import Table
from rich.text import Text


def _build_table() -> Table:
    tbl = Table(
        show_header=True,
        show_footer=True,
        show_lines=True,
        show_edge=True,
        leading=0,
        expand=False,
    )
    tbl.add_column("A", justify="left", vertical="top")
    tbl.add_column("B", justify="center", vertical="middle")
    tbl.add_column("C", justify="right", vertical="bottom")
    tbl.add_column("D", justify="full")

    seed = 0x2a7f3c91
    for row_idx in range(24):
        lines_per_col = [
            1 + ((row_idx * 3 + seed) % 4),
            1 + ((row_idx * 5 + seed) % 3),
            1 + ((row_idx * 7 + seed) % 5),
            1 + ((row_idx * 11 + seed) % 2),
        ]
        cells = []
        for col_idx, line_count in enumerate(lines_per_col):
            token = (row_idx * 13 + col_idx * 23 + seed) % 997
            body = "\n".join(
                f"x{token + line_no * 19}" for line_no in range(line_count)
            )
            cells.append(Text(body))
        end_section = (row_idx % 5 == 2) and row_idx > 0
        style = "bold" if row_idx % 7 == 4 else None
        tbl.add_row(*cells, end_section=end_section, style=style)

    tbl.columns[0].footer = Text("ftr0")
    tbl.columns[1].footer = Text("ftr1")
    tbl.columns[2].footer = Text("ftr2")
    tbl.columns[3].footer = Text("ftr3")
    return tbl


class TableRenderS3StateTest(unittest.TestCase):
    def test_table_render_state_harvest(self) -> None:
        table = _build_table()
        console = Console(
            width=88,
            legacy_windows=False,
            color_system=None,
            force_terminal=True,
            record=True,
        )
        options = console.options
        widths = table._calculate_column_widths(
            console, options.update_width(console.width)
        )
        table_width = sum(widths) + table._extra_width
        render_options = options.update(
            width=table_width, highlight=table.highlight, height=None
        )
        segments = list(table._render(console, render_options, widths))
        self.assertGreater(len(segments), 50)
        self.assertGreater(sum(widths), 8)
        self.assertEqual(len(table.rows), 24)

