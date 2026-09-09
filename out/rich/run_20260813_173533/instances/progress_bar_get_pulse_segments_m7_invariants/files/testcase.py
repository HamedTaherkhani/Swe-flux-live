import hashlib
import unittest

from rich.color import Color
from rich.progress_bar import ProgressBar
from rich.style import Style


def _seed_digest(label: str, nbytes: int = 32) -> bytes:
    return hashlib.sha256(f"pulse-segments-m7-{label}".encode()).digest() * (
        (nbytes // 32) + 1
    )


def _rgb_from_digest(raw: bytes, offset: int) -> tuple[int, int, int]:
    base = offset % (len(raw) - 2)
    return (
        raw[base] % 220 + 10,
        raw[base + 1] % 220 + 10,
        raw[base + 2] % 220 + 10,
    )


def _style_from_digest(raw: bytes, offset: int) -> Style:
    red, green, blue = _rgb_from_digest(raw, offset)
    return Style(color=Color.from_rgb(red, green, blue))


def _segments_digest(segments: object) -> str:
    return hashlib.sha256(repr(segments).encode()).hexdigest()


class ProgressBarGetPulseSegmentsInvariantsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bar = ProgressBar()

    def _call_pulse(
        self,
        fore: Style,
        back: Style,
        color_system: str,
        *,
        ascii: bool = False,
    ) -> None:
        self.bar._get_pulse_segments.cache_clear()
        segments = self.bar._get_pulse_segments(
            fore, back, color_system, False, ascii=ascii
        )
        digest = _segments_digest(segments)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))

    def test_truecolor_batch_alpha(self) -> None:
        raw = _seed_digest("truecolor-alpha", 96)
        for slot in range(6):
            fore = _style_from_digest(raw, slot * 3)
            back = _style_from_digest(raw, slot * 3 + 9)
            self._call_pulse(fore, back, "truecolor", ascii=slot % 2 == 1)

    def test_truecolor_batch_beta(self) -> None:
        raw = _seed_digest("truecolor-beta", 80)
        for slot in range(5):
            fore = _style_from_digest(raw, slot * 4 + 1)
            back = _style_from_digest(raw, slot * 4 + 13)
            self._call_pulse(fore, back, "truecolor", ascii=slot % 3 == 0)

    def test_standard_palette_gamma(self) -> None:
        raw = _seed_digest("standard-gamma", 72)
        for slot in range(7):
            fore = _style_from_digest(raw, slot * 2)
            back = _style_from_digest(raw, slot * 2 + 17)
            self._call_pulse(fore, back, "standard", ascii=False)

    def test_eight_bit_palette_delta(self) -> None:
        raw = _seed_digest("eight-bit-delta", 88)
        for slot in range(6):
            fore = _style_from_digest(raw, slot * 5)
            back = _style_from_digest(raw, slot * 5 + 11)
            self._call_pulse(fore, back, "eight_bit", ascii=slot % 2 == 0)

    def test_ascii_true_epsilon(self) -> None:
        raw = _seed_digest("ascii-true-epsilon", 64)
        for slot in range(8):
            fore = _style_from_digest(raw, slot * 3 + 2)
            back = _style_from_digest(raw, slot * 3 + 20)
            self._call_pulse(fore, back, "standard", ascii=True)

    def test_ascii_false_zeta(self) -> None:
        raw = _seed_digest("ascii-false-zeta", 56)
        for slot in range(6):
            fore = _style_from_digest(raw, slot * 6)
            back = _style_from_digest(raw, slot * 6 + 7)
            self._call_pulse(fore, back, "truecolor", ascii=False)

    def test_mixed_ascii_calls_eta(self) -> None:
        raw = _seed_digest("mixed-ascii-eta", 104)
        systems = ("standard", "eight_bit", "truecolor")
        for slot in range(9):
            fore = _style_from_digest(raw, slot * 4)
            back = _style_from_digest(raw, slot * 4 + 23)
            self._call_pulse(
                fore,
                back,
                systems[slot % len(systems)],
                ascii=(slot + 1) % 4 == 0,
            )

    def test_fore_without_color_theta(self) -> None:
        raw = _seed_digest("fore-no-color-theta", 48)
        for slot in range(5):
            fore = Style()
            back = _style_from_digest(raw, slot * 7 + 3)
            self._call_pulse(fore, back, "truecolor", ascii=slot % 2 == 1)

    def test_back_without_color_iota(self) -> None:
        raw = _seed_digest("back-no-color-iota", 60)
        for slot in range(6):
            fore = _style_from_digest(raw, slot * 5 + 1)
            back = Style()
            self._call_pulse(fore, back, "eight_bit", ascii=False)

    def test_deep_batch_kappa(self) -> None:
        raw = _seed_digest("deep-batch-kappa", 128)
        for slot in range(10):
            fore = _style_from_digest(raw, slot * 3)
            back = _style_from_digest(raw, slot * 3 + 31)
            self._call_pulse(
                fore,
                back,
                ("standard", "truecolor")[slot % 2],
                ascii=slot % 5 == 2,
            )

    def test_complement_pairs_lambda(self) -> None:
        raw = _seed_digest("complement-lambda", 76)
        for slot in range(7):
            red, green, blue = _rgb_from_digest(raw, slot * 3)
            fore = Style(color=Color.from_rgb(red, green, blue))
            back = Style(color=Color.from_rgb(255 - red, 255 - green, 255 - blue))
            self._call_pulse(
                fore,
                back,
                ("truecolor", "standard", "eight_bit")[slot % 3],
                ascii=slot % 3 == 1,
            )

    def test_hue_sweep_mu(self) -> None:
        raw = _seed_digest("hue-sweep-mu", 112)
        for slot in range(8):
            fore = _style_from_digest(raw, slot * 4)
            back = _style_from_digest(raw, slot * 4 + 29)
            self._call_pulse(
                fore,
                back,
                ("standard", "eight_bit", "truecolor")[slot % 3],
                ascii=slot % 4 == 3,
            )
