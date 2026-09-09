"""Indirect exercise of grapheme cell measurement via set_cell_size and Text.truncate."""

from __future__ import annotations

import unittest

from rich.cells import set_cell_size
from rich.text import Text

ZWJ = "\u200d"
VS16 = "\ufe0f"
FAMILY = ["\U0001f468", "\U0001f469", "\U0001f467", "\U0001f466"]
EMOJI = ["\U0001f600", "\U0001f389", "\U0001f525", "\U0001f4af", "\U0001f31f"]


def _build_complex_text(seed: int, units: int) -> str:
    rng = __import__("random").Random(seed)
    parts: list[str] = []
    for index in range(units):
        base = EMOJI[(index + seed) % len(EMOJI)]
        mode = (index + seed + rng.randint(0, 2)) % 7
        if mode == 0:
            parts.append(ZWJ.join(FAMILY))
        elif mode == 1:
            parts.append(base + VS16)
        elif mode == 2:
            parts.append(ZWJ * (1 + index % 3))
        elif mode == 3:
            parts.append(base)
        elif mode == 4:
            parts.append(VS16)
        elif mode == 5:
            parts.append(base + ZWJ + FAMILY[index % len(FAMILY)])
        else:
            parts.append("".join(FAMILY[:2]) + VS16 + ZWJ + base)
    return "".join(parts)


def _invoke_resize(text: str, target: int, *, unicode_version: str = "auto") -> int:
    return len(set_cell_size(text, target, unicode_version=unicode_version))


def _invoke_truncate(text: str, max_width: int) -> int:
    rendered = Text(text)
    rendered.truncate(max_width, overflow="crop")
    return len(rendered.plain)


class TestCellLenInvariants(unittest.TestCase):
    def test_alternating_joiner_runs(self) -> None:
        payload = _build_complex_text(0x1000, 41)
        width = _invoke_resize(payload, 52 + (len(payload) % 11))
        self.assertGreater(width, len(payload) // 4)

    def test_crop_via_text_truncate(self) -> None:
        payload = _build_complex_text(0x1111, 48)
        width = _invoke_truncate(payload, 36 + (len(payload) % 9))
        self.assertGreater(width, 0)
        self.assertLessEqual(width, len(payload))

    def test_dense_family_blocks(self) -> None:
        payload = _build_complex_text(0x1222, 55)
        width = _invoke_resize(payload, 61 + (len(payload) % 13))
        self.assertGreater(width, 20)

    def test_expand_padding_target(self) -> None:
        payload = _build_complex_text(0x1333, 62)
        width = _invoke_resize(payload, 88 + (len(payload) % 7))
        self.assertGreater(width, len(payload) // 3)

    def test_fe0f_suffix_clusters(self) -> None:
        payload = _build_complex_text(0x1444, 69)
        width = _invoke_resize(payload, 74 + (len(payload) % 5))
        self.assertGreater(width, 15)

    def test_joiner_only_segments(self) -> None:
        payload = _build_complex_text(0x1555, 76)
        width = _invoke_resize(payload, 80 + (len(payload) % 17))
        self.assertGreater(width, 10)

    def test_mixed_emoji_walk(self) -> None:
        payload = _build_complex_text(0x1666, 83)
        width = _invoke_resize(payload, 95 + (len(payload) % 19))
        self.assertGreater(width, 25)

    def test_programmatic_zwj_ladder(self) -> None:
        payload = _build_complex_text(0x1777, 90)
        width = _invoke_resize(payload, 101 + (len(payload) % 23))
        self.assertGreater(width, 30)

    def test_repeated_vs16_pairs(self) -> None:
        payload = _build_complex_text(0x1888, 97)
        width = _invoke_resize(payload, 109 + (len(payload) % 3))
        self.assertGreater(width, 35)

    def test_shrink_to_narrow_budget(self) -> None:
        payload = _build_complex_text(0x1999, 44)
        width = _invoke_resize(payload, 27 + (len(payload) % 6))
        self.assertGreater(width, 0)
        self.assertLess(width, len(payload))

    def test_stretch_wide_field(self) -> None:
        payload = _build_complex_text(0x1AAA, 51)
        width = _invoke_resize(payload, 120 + (len(payload) % 8))
        self.assertGreater(width, len(payload) // 2)

    def test_variation_selector_chain(self) -> None:
        payload = _build_complex_text(0x1BBB, 58)
        width = _invoke_resize(payload, 66 + (len(payload) % 10), unicode_version="latest")
        self.assertGreater(width, 18)
