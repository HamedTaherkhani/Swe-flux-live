"""Direct exercise of ratio_resolve with many flexible edges and minimums."""

from __future__ import annotations

import random
import unittest
from dataclasses import dataclass
from typing import Optional

from rich._ratio import ratio_resolve


@dataclass
class FlexEdge:
    size: Optional[int] = None
    ratio: int = 1
    minimum_size: int = 1


def _build_edges(seed: int) -> tuple[int, list[FlexEdge]]:
    """Construct a large edge list with mixed fixed and flexible entries."""
    rng = random.Random(seed)
    count = 75 + (seed % 29)
    edges: list[FlexEdge] = []
    for index in range(count):
        ratio = 1 + (index % 19)
        minimum_size = (
            8 + (index * 13) % 37 + (index // 3) * 5 + rng.randint(0, 4)
        )
        if index % 4 == 0 and index > 0:
            fixed = minimum_size + (index * 3) % 17
            edges.append(FlexEdge(fixed, ratio, minimum_size))
        else:
            edges.append(FlexEdge(None, ratio, minimum_size))
    minimum_total = sum(edge.minimum_size for edge in edges)
    fixed_total = sum(edge.size or 0 for edge in edges)
    total = minimum_total + fixed_total + 1500 + (seed % 113)
    return total, edges


class TestRatioResolveLoops(unittest.TestCase):
    def test_ratio_resolve_flexible_minimums(self) -> None:
        total, edges = _build_edges(0xDEAD)
        resolved = ratio_resolve(total, edges)

        self.assertEqual(len(resolved), len(edges))
        self.assertEqual(sum(resolved), total)
        self.assertTrue(all(value >= 1 for value in resolved))
        for value, edge in zip(resolved, edges):
            self.assertGreaterEqual(value, edge.minimum_size)
        self.assertGreater(max(resolved) - min(resolved), 3)
        self.assertGreater(
            sum(1 for edge in edges if edge.size is None),
            len(edges) // 3,
        )