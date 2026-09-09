import hashlib
import string
import unittest

from rich.console import Console
from rich.containers import Lines
from rich.text import Text


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"containers-justify-m7-{label}".encode()).digest() * (
        (count // 32) + 1
    )


def _digest_lines(lines: Lines) -> str:
    payload = "|".join(line.plain for line in lines)
    return hashlib.sha256(payload.encode()).hexdigest()


_ALPHA = len(string.ascii_lowercase)


def _word_from_seed(raw: bytes, index: int) -> str:
    length = (raw[index] % 4) + 2
    base = chr(97 + (raw[index + 1] % _ALPHA))
    return base * length


def _build_word_line(seed: str, word_count: int) -> Text:
    raw = _seed_bytes(seed, word_count * 2 + 8)
    words = [_word_from_seed(raw, index * 2) for index in range(word_count)]
    return Text(" ".join(words))


def _styled_word_line(seed: str, word_count: int) -> Text:
    raw = _seed_bytes(seed, word_count * 3 + 12)
    parts: list[Text] = []
    styles = ["bold", "italic", "underline", "dim", "reverse"]
    for index in range(word_count):
        word = _word_from_seed(raw, index * 3)
        style = styles[(raw[index * 3 + 1] + index) % len(styles)]
        parts.append(Text(word, style=style))
        if index + 1 < word_count:
            parts.append(Text(" "))
    return Text("").join(parts)


class ContainersJustifyInvariantsTest(unittest.TestCase):
    def _run_justify(
        self,
        lines: Lines,
        width: int,
        justify: str,
        overflow: str = "fold",
    ) -> None:
        console = Console(width=width, force_terminal=True, legacy_windows=False)
        lines.justify(console, width, justify=justify, overflow=overflow)
        digest = _digest_lines(lines)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))

    def test_full_justify_dense_words_alpha(self) -> None:
        body = [_build_word_line("full-alpha", 8) for _ in range(6)]
        lines = Lines(body)
        self._run_justify(lines, 28, "full")

    def test_full_justify_dense_words_beta(self) -> None:
        body = [_build_word_line("full-beta", 10) for _ in range(5)]
        lines = Lines(body)
        self._run_justify(lines, 24, "full")

    def test_full_justify_narrow_width_gamma(self) -> None:
        body = [_build_word_line("full-gamma", 12) for _ in range(4)]
        lines = Lines(body)
        self._run_justify(lines, 19, "full")

    def test_full_justify_styled_words_delta(self) -> None:
        body = [_styled_word_line("styled-delta", 7) for _ in range(5)]
        lines = Lines(body)
        self._run_justify(lines, 27, "full")

    def test_full_justify_styled_words_epsilon(self) -> None:
        body = [_styled_word_line("styled-epsilon", 9) for _ in range(4)]
        lines = Lines(body)
        self._run_justify(lines, 22, "full")

    def test_full_justify_single_token_lines(self) -> None:
        raw = _seed_bytes("single-token", 48)
        body = [Text(chr(97 + (raw[index] % _ALPHA)) * ((raw[(index + 5) % len(raw)] % 5) + 3))
                for index in range(12)]
        lines = Lines(body)
        self._run_justify(lines, 13, "full")

    def test_full_justify_mixed_lengths_zeta(self) -> None:
        raw = _seed_bytes("mixed-zeta", 64)
        body: list[Text] = []
        for index in range(8):
            count = (raw[index] % 6) + 3
            body.append(_build_word_line(f"mixed-zeta-{index}", count))
        lines = Lines(body)
        self._run_justify(lines, 32, "full")

    def test_full_justify_overflow_crop_eta(self) -> None:
        body = [_build_word_line("crop-eta", 6) for _ in range(6)]
        lines = Lines(body)
        self._run_justify(lines, 17, "full", overflow="crop")

    def test_center_justify_various_theta(self) -> None:
        raw = _seed_bytes("center-theta", 56)
        body = [
            Text(chr(65 + (raw[index] % _ALPHA)) * ((raw[index + 20] % 7) + 2))
            for index in range(9)
        ]
        lines = Lines(body)
        self._run_justify(lines, 12, "center")

    def test_center_justify_overflow_ellipsis_iota(self) -> None:
        body = [_build_word_line("center-iota", 5) for _ in range(6)]
        lines = Lines(body)
        self._run_justify(lines, 10, "center", overflow="ellipsis")

    def test_right_justify_various_kappa(self) -> None:
        raw = _seed_bytes("right-kappa", 48)
        body = [
            Text(chr(97 + (raw[index] % _ALPHA)) * ((raw[index + 12] % 6) + 1))
            for index in range(14)
        ]
        lines = Lines(body)
        self._run_justify(lines, 11, "right")

    def test_right_justify_overflow_fold_lambda(self) -> None:
        body = [_styled_word_line("right-lambda", 4) for _ in range(10)]
        lines = Lines(body)
        self._run_justify(lines, 13, "right", overflow="fold")
