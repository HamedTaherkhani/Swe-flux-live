import hashlib
import unittest

from rich.box import MINIMAL, ROUNDED, SQUARE


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"box-get-row-s3-{label}".encode()).digest() * (
        (count // 32) + 1
    )


def _build_widths(seed: str, count: int) -> list[int]:
    raw = _seed_bytes(seed, count)
    return [((raw[index] + index * 3) % 8) + 1 for index in range(count)]


def _pick_box(seed: str):
    boxes = (SQUARE, ROUNDED, MINIMAL)
    raw = _seed_bytes(seed, 1)
    return boxes[raw[0] % len(boxes)]


def _result_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class BoxGetRowProgramStateTest(unittest.TestCase):
    def test_seeded_get_row_foot_level(self) -> None:
        box = _pick_box("foot-row")
        raw = _seed_bytes("foot-widths", 4)
        width_count = 17 + (raw[0] % 6)
        widths = _build_widths("foot-widths", width_count)
        row = box.get_row(widths, level="foot", edge=True)
        digest = _result_digest(row)
        self.assertEqual(len(digest), 64)
        self.assertGreater(len(row), sum(widths))
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))
