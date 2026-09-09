"""Direct exercise of Segment.divide with seeded segment and cut streams."""

from __future__ import annotations

import unittest

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style


def _build_segment_batch(seed: int, batch_size: int) -> list[Segment]:
    rng = __import__("random").Random(seed)
    segments: list[Segment] = []
    for index in range(batch_size):
        mode = (seed + index * 3) % 6
        if mode == 0:
            text = "".join(
                chr(97 + (seed + index + offset) % 26) for offset in range(2 + index % 5)
            )
        elif mode == 1:
            text = "\U0001f600" * (1 + index % 2) + "m" * (1 + index % 4)
        elif mode == 2:
            text = " " * (index % 4) + "Q" * (3 + index % 6)
        elif mode == 3:
            text = "\t" + "r" * (2 + index % 5)
        elif mode == 4:
            text = "".join(
                chr(65 + (index + offset) % 26) for offset in range(4 + index % 4)
            )
        else:
            text = "x" * (1 + index % 3) + "\U0001f525" + "y" * (index % 2)
        style = Style(color="cyan", bold=index % 2 == 0) if index % 3 != 1 else None
        control = [(1,)] if index % 9 == 0 else None
        segments.append(Segment(text, style, control))
    rng.shuffle(segments)
    return segments


def _build_cut_stream(segments: list[Segment], seed: int) -> list[int]:
    rng = __import__("random").Random(seed)
    cursor = 0
    boundary_positions: list[int] = []
    for segment in segments:
        _text, _style, control = segment
        if control:
            boundary_positions.append(cursor)
            continue
        cursor += cell_len(segment.text)
        boundary_positions.append(cursor)

    leading_zeros = [0] * (2 + seed % 3)
    interior = list(range(1, max(cursor, 1)))
    rng.shuffle(interior)
    pick_count = min(len(interior), 28 + seed % 9)
    selected = sorted(interior[:pick_count])

    for boundary in boundary_positions:
        if boundary > 0 and rng.random() < 0.35 and boundary not in selected:
            selected.append(boundary)

    return leading_zeros + sorted(set(selected))


def _checksum_chunks(chunks: list[list[Segment]]) -> int:
    total = 0
    for chunk_index, chunk in enumerate(chunks):
        for segment_index, segment in enumerate(chunk):
            total += (chunk_index + 1) * (segment_index + 3) + cell_len(segment.text)
            if segment.control is not None:
                total += 7
    return total


class TestSegmentDivideDataFlow(unittest.TestCase):
    def test_divide_dataflow(self) -> None:
        seed = 0xC0DE
        segments = _build_segment_batch(seed, 22 + seed % 5)
        cuts = _build_cut_stream(segments, seed + 17)
        chunks = list(Segment.divide(segments, cuts))
        self.assertGreater(len(chunks), 12)
        self.assertGreater(sum(len(chunk) for chunk in chunks), len(segments))
        digest = _checksum_chunks(chunks)
        self.assertGreater(digest, len(segments) * 4)
        self.assertGreater(len(chunks), len(cuts) // 2)
