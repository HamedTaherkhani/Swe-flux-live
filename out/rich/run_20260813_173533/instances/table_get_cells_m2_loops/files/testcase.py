"""Exercise table rendering through Console.print (indirect path to cell assembly)."""

from __future__ import annotations

import io
import random
import unittest

from rich.console import Console
from rich.table import Table


def _row_count(seed: int, slot: int) -> int:
    rng = random.Random(seed ^ (slot * 0x9E3779B1))
    return 1 + rng.randrange(55)


def _seeded_rows(rng: random.Random, count: int, cols: int) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for row_idx in range(count):
        cells: list[str] = []
        for col_idx in range(cols):
            token = (row_idx * 17 + col_idx * 31 + rng.randrange(97)) % 997
            cells.append(f"c{col_idx}r{row_idx}t{token}")
        rows.append(tuple(cells))
    return rows


def _build_and_render(
    *,
    row_count: int,
    col_count: int,
    seed: int,
    show_header: bool = True,
    show_footer: bool = True,
    padding: tuple[int, int, int, int] = (0, 1, 0, 1),
    collapse_padding: bool = False,
    pad_edge: bool = True,
    expand: bool = False,
) -> str:
    rng = random.Random(seed)
    headers = tuple(f"H{idx}" for idx in range(col_count))
    footers = tuple(f"F{idx}" for idx in range(col_count))
    table = Table(
        show_header=show_header,
        show_footer=show_footer,
        padding=padding,
        collapse_padding=collapse_padding,
        pad_edge=pad_edge,
        expand=expand,
    )
    for header, footer in zip(headers, footers):
        table.add_column(header, footer=footer)
    for row in _seeded_rows(rng, row_count, col_count):
        table.add_row(*row)
    out = io.StringIO()
    console = Console(file=out, width=140, color_system=None, force_terminal=False)
    console.print(table)
    return out.getvalue()


class TestTableGetCellsLoopDynamics(unittest.TestCase):
    def _print_and_check(self, rendered: str, min_len: int) -> None:
        self.assertGreater(len(rendered), min_len)
        self.assertTrue(rendered.strip())

    def test_sparse_single_row(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xA11, 5), col_count=2, seed=0xA11
        )
        self._print_and_check(rendered, 4)

    def test_compact_three_by_three(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xB22, 31), col_count=3, seed=0xB22
        )
        self._print_and_check(rendered, 12)

    def test_medium_grid_no_header(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xC33, 71),
            col_count=4,
            seed=0xC33,
            show_header=False,
        )
        self._print_and_check(rendered, 20)

    def test_medium_grid_no_footer(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xD44, 11),
            col_count=3,
            seed=0xD44,
            show_footer=False,
        )
        self._print_and_check(rendered, 24)

    def test_body_only_layout(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xE55, 0),
            col_count=5,
            seed=0xE55,
            show_header=False,
            show_footer=False,
        )
        self._print_and_check(rendered, 30)

    def test_zero_padding_wide(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0xF66, 4),
            col_count=6,
            seed=0xF66,
            padding=(0, 0, 0, 0),
        )
        self._print_and_check(rendered, 40)

    def test_collapsed_padding_tall(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x107, 3),
            col_count=4,
            seed=0x107,
            padding=(1, 2, 1, 2),
            collapse_padding=True,
        )
        self._print_and_check(rendered, 50)

    def test_unpadded_edges_dense(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x208, 14),
            col_count=3,
            seed=0x208,
            pad_edge=False,
            padding=(1, 1, 1, 1),
        )
        self._print_and_check(rendered, 55)

    def test_expanded_many_columns(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x309, 94),
            col_count=8,
            seed=0x309,
            expand=True,
        )
        self._print_and_check(rendered, 35)

    def test_long_body_few_columns(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x40A, 51),
            col_count=2,
            seed=0x40A,
        )
        self._print_and_check(rendered, 60)

    def test_balanced_large_block(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x50B, 40),
            col_count=5,
            seed=0x50B,
            padding=(0, 2, 0, 2),
        )
        self._print_and_check(rendered, 80)

    def test_maximum_volume_case(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x60C, 7),
            col_count=7,
            seed=0x60C,
            padding=(1, 1, 1, 1),
            collapse_padding=True,
            pad_edge=False,
        )
        self._print_and_check(rendered, 120)

    def test_mixed_padding_footerless(self) -> None:
        rendered = _build_and_render(
            row_count=_row_count(0x70D, 86),
            col_count=4,
            seed=0x70D,
            show_footer=False,
            padding=(2, 0, 2, 0),
        )
        self._print_and_check(rendered, 70)
