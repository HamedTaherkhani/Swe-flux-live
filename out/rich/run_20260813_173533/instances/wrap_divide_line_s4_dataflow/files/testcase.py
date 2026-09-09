"""Direct exercise of divide_line with seeded word streams."""

from __future__ import annotations

import unittest

from rich._wrap import divide_line
from rich.cells import cell_len


def _build_word_stream(seed: int, token_count: int) -> list[str]:
    rng = __import__("random").Random(seed)
    tokens: list[str] = []
    for index in range(token_count):
        lane = (seed + index * 13) % 9
        if lane == 0:
            piece = "".join(
                chr(97 + (seed + index + offset) % 26)
                for offset in range(2 + index % 4)
            )
        elif lane == 1:
            piece = "Q" * (9 + index % 11)
        elif lane == 2:
            piece = "\U0001f680" * (1 + index % 2) + "k" * (1 + index % 3)
        elif lane == 3:
            piece = "to"
        elif lane == 4:
            piece = "mnopqrstuvwxyzAB"
        elif lane == 5:
            piece = " " + "v" * (2 + index % 6)
        elif lane == 6:
            piece = "mix" + chr(65 + index % 26)
        elif lane == 7:
            piece = "w" * (5 + index % 9)
        else:
            piece = "edge" + "".join(
                chr(48 + (index + offset) % 10) for offset in range(3 + index % 4)
            )
        tokens.append(piece)
    rng.shuffle(tokens)
    return tokens


def _compose_line(tokens: list[str], seed: int) -> str:
    rng = __import__("random").Random(seed + 3)
    parts: list[str] = []
    for index, token in enumerate(tokens):
        if index and rng.random() < 0.18:
            parts.append("  ")
        parts.append(token)
    return "".join(parts)


def _break_digest(breaks: list[int], seed: int) -> int:
    total = seed & 0xFF
    for index, position in enumerate(breaks):
        total += ((index + 3) * (position + 1)) ^ (seed >> (index % 5))
    return total


class TestDivideLineDataFlow(unittest.TestCase):
    def test_divide_line_dataflow(self) -> None:
        seed = 0xD15EA5E
        tokens = _build_word_stream(seed, 31 + (seed % 5))
        text = _compose_line(tokens, seed + 9)
        width = 6 + ((seed >> 4) % 7)
        breaks = divide_line(text, width, fold=True)
        self.assertGreater(len(breaks), len(tokens) // 3)
        self.assertGreater(sum(cell_len(text[offset:]) for offset in breaks[:1]), 0)
        digest = _break_digest(breaks, seed)
        self.assertGreater(digest, len(text) + (seed % 97))
        self.assertGreater(len({offset % width for offset in breaks}), 1)
