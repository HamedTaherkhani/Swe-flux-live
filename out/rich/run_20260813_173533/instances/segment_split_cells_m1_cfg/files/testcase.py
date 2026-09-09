"""Exercise segment column splitting indirectly through Segment.divide."""

from __future__ import annotations

import random
import unittest

from rich.segment import Segment
from rich.style import Style


def _style(seed: int) -> Style:
    rng = random.Random(seed)
    tokens = ("bold", "italic", "underline", "dim")
    picked = tokens[rng.randrange(len(tokens))]
    return Style.parse(picked)


def _wide_chunk(rng: random.Random, tag: int) -> str:
    pool = ("你", "好", "世", "界", "🎉", "🌟", "é", "ñ", "中", "文")
    return pool[(tag + rng.randrange(len(pool))) % len(pool)]


def _build_wide_text(rng: random.Random, length: int) -> str:
    parts: list[str] = []
    for idx in range(length):
        bucket = (idx * 3 + rng.randrange(5)) % 4
        if bucket == 0:
            parts.append(chr(ord("a") + (idx % 26)))
        elif bucket == 1:
            parts.append(_wide_chunk(rng, idx))
        elif bucket == 2:
            parts.append(chr(ord("A") + (idx % 26)))
        else:
            parts.append(_wide_chunk(rng, idx + 7))
    return "".join(parts)


def _family_emoji_text(rng: random.Random) -> str:
    prefix = _build_wide_text(rng, 2 + rng.randrange(3))
    core = "👨\u200d👩\u200d👧\u200d👦"
    suffix = _build_wide_text(rng, 1 + rng.randrange(4))
    return prefix + core + suffix


def _run_divide(text: str, cuts: list[int], style: Style | None = None) -> list[list[Segment]]:
    Segment._split_cells.cache_clear()
    segment = Segment(text, style or Style())
    portions = list(Segment.divide([segment], cuts))
    return portions


def _portion_text_len(portions: list[list[Segment]]) -> int:
    return sum(len("".join(seg.text for seg in group)) for group in portions)


class TestSegmentDivideSplitCellsFlow(unittest.TestCase):
    def test_cut_beyond_segment_width(self) -> None:
        rng = random.Random(0xA01)
        text = _build_wide_text(rng, 6)
        cell_total = Segment(text).cell_length
        cuts = [cell_total + 1 + rng.randrange(4)]
        portions = _run_divide(text, cuts, _style(0xA01))
        self.assertEqual(len(portions), 1)
        self.assertGreater(_portion_text_len(portions), 0)

    def test_exact_boundary_on_wide_prefix(self) -> None:
        rng = random.Random(0xA02)
        text = "你" + _build_wide_text(rng, 5)
        portions = _run_divide(text, [2], _style(0xA02))
        self.assertEqual(len(portions), 1)
        self.assertTrue(portions[0])
        self.assertLessEqual(Segment(text).cell_length, len(text) + 4)

    def test_split_inside_first_wide_character(self) -> None:
        rng = random.Random(0xA03)
        text = _wide_chunk(rng, 1) + _build_wide_text(rng, 7)
        portions = _run_divide(text, [1], _style(0xA03))
        self.assertEqual(len(portions), 1)
        self.assertTrue(any(" " in seg.text for group in portions for seg in group))

    def test_split_after_double_width_pair(self) -> None:
        rng = random.Random(0xA04)
        text = "你" + _wide_chunk(rng, 2) + "ab" + _wide_chunk(rng, 3)
        portions = _run_divide(text, [3], _style(0xA04))
        self.assertEqual(len(portions), 1)
        self.assertTrue(portions[0])

    def test_multiple_cuts_on_single_segment(self) -> None:
        rng = random.Random(0xA05)
        text = _build_wide_text(rng, 9)
        cell_total = Segment(text).cell_length
        cuts = [
            1 + rng.randrange(2),
            cell_total // 2,
            cell_total - 1,
        ]
        portions = _run_divide(text, cuts, _style(0xA05))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), len(text) // 2)

    def test_emoji_family_adjustment_path(self) -> None:
        rng = random.Random(0xA06)
        text = _family_emoji_text(rng)
        cell_total = Segment(text).cell_length
        cut = 3 + rng.randrange(max(1, cell_total // 3))
        portions = _run_divide(text, [cut], _style(0xA06))
        self.assertEqual(len(portions), 1)
        self.assertIn(" ", "".join(seg.text for group in portions for seg in group))

    def test_alternating_width_run(self) -> None:
        rng = random.Random(0xA07)
        chunks = [_wide_chunk(rng, idx) if idx % 2 else chr(ord("a") + idx) for idx in range(8)]
        text = "".join(chunks)
        cuts = [2, 5, 7]
        portions = _run_divide(text, cuts, _style(0xA07))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), len(cuts))

    def test_long_wide_sequence_many_cuts(self) -> None:
        rng = random.Random(0xA08)
        text = _build_wide_text(rng, 18)
        cell_total = Segment(text).cell_length
        cuts = sorted(
            {
                1 + rng.randrange(max(1, cell_total - 1))
                for _ in range(12)
            }
        )
        portions = _run_divide(text, cuts, _style(0xA08))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), cell_total // 2)

    def test_two_segments_shared_cut_stream(self) -> None:
        rng = random.Random(0xA09)
        left = _build_wide_text(rng, 5)
        right = _build_wide_text(rng, 6)
        cuts = [3, 6, 9]
        Segment._split_cells.cache_clear()
        portions = list(
            Segment.divide(
                [Segment(left, _style(0xA09)), Segment(right, _style(0xA09))],
                cuts,
            )
        )
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), len(left))

    def test_seeded_portion_batch(self) -> None:
        rng = random.Random(0xA0A)
        batch = [_build_wide_text(rng, 4 + rng.randrange(6)) for _ in range(4)]
        cuts = [2, 4, 6, 8]
        Segment._split_cells.cache_clear()
        segments = [Segment(item, _style(0xA0A + idx)) for idx, item in enumerate(batch)]
        portions = list(Segment.divide(segments, cuts))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), len(batch))

    def test_dense_cut_grid(self) -> None:
        rng = random.Random(0xA0B)
        text = _build_wide_text(rng, 14)
        cell_total = Segment(text).cell_length
        cuts = list(range(1, min(cell_total, 16), 2))
        portions = _run_divide(text, cuts, _style(0xA0B))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(len(portions), 2)

    def test_mixed_scripts_and_symbols(self) -> None:
        rng = random.Random(0xA0C)
        text = "a你b🎉c" + _build_wide_text(rng, 8) + "d世e"
        cell_total = Segment(text).cell_length
        cuts = [
            2,
            4,
            cell_total // 3,
            cell_total - 2,
        ]
        portions = _run_divide(text, cuts, _style(0xA0C))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), 6)

    def test_programmatic_cut_walk(self) -> None:
        rng = random.Random(0xA0D)
        text = _family_emoji_text(rng) + _build_wide_text(rng, 6)
        cell_total = Segment(text).cell_length
        cuts = []
        step = 1 + rng.randrange(2)
        pos = step
        while pos < cell_total:
            cuts.append(pos)
            pos += step + rng.randrange(2)
        portions = _run_divide(text, cuts, _style(0xA0D))
        self.assertEqual(len(portions), len(cuts))
        self.assertGreater(_portion_text_len(portions), step)
