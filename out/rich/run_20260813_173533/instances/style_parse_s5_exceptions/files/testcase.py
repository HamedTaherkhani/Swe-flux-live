"""Exercise style normalization with programmatic style specifications."""

from __future__ import annotations

import random
import unittest

from rich.style import Style


class TestStyleNormalizeIndirectParse(unittest.TestCase):
    def test_normalize_programmatic_style_specs(self) -> None:
        rng = random.Random(0x51E5)
        attribute_pool = [
            "bold",
            "italic",
            "underline",
            "dim",
            "reverse",
            "blink",
            "strike",
            "conceal",
        ]
        color_pool = [
            "red",
            "green",
            "blue",
            "yellow",
            "#112233",
            "#445566",
            "color(17)",
            "color(200)",
            "rgb(10,20,30)",
            "rgb(40,50,60)",
        ]

        specs: list[str] = []
        for idx in range(24):
            chunk: list[str] = []
            attr_count = 2 + (idx % 5)
            for attr_idx in range(attr_count):
                chunk.append(attribute_pool[(idx * 3 + attr_idx * 5) % len(attribute_pool)])
            if idx % 4 != 1:
                chunk.append(color_pool[(idx * 7) % len(color_pool)])
            if idx % 3 == 0:
                chunk.append("on")
                chunk.append(color_pool[(idx * 11 + 3) % len(color_pool)])
            if idx % 5 == 2:
                chunk.append("link")
                chunk.append(f"https://example.org/{idx}/{rng.randrange(1000, 9999)}")
            specs.append(" ".join(chunk))

        fault_index = 11 + (rng.randrange(4) + rng.randrange(3))
        fault_token = f"q{rng.getrandbits(36):09x}"
        fault_spec = " ".join(
            [
                attribute_pool[fault_index % len(attribute_pool)],
                "on",
                fault_token,
            ]
        )
        specs.insert(fault_index, fault_spec)

        normalized: list[str] = []
        for spec in specs:
            normalized.append(Style.normalize(spec))

        self.assertEqual(len(normalized), len(specs))
        self.assertTrue(all(isinstance(item, str) for item in normalized))
        self.assertEqual(normalized[fault_index], fault_spec.strip().lower())
        self.assertGreater(sum(len(item) for item in normalized), len(specs) * 3)
        valid_hits = sum(
            1 for idx, item in enumerate(normalized) if idx != fault_index and item
        )
        self.assertGreater(valid_hits, 18)
