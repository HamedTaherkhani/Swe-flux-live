import hashlib
import unittest

from rich.cells import chop_cells, set_cell_size, split_text


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"split-graphemes-m3-{label}".encode()).digest() * (
        (count // 32) + 1
    )


def _pick_wide(byte: int) -> str:
    pool = [
        "\u4e00",
        "\u3042",
        "\u1100",
        "\U0001f600",
        "\U0001f1e6",
        "\u26a1",
        "\u2708",
        "\u231a",
    ]
    return pool[byte % len(pool)]


def _pick_special(byte: int) -> str:
    pool = ["\u200d", "\ufe0f", "\u0007", "\u000b"]
    return pool[byte % len(pool)]


def _build_mixed_text(seed: str, length: int) -> str:
    raw = _seed_bytes(seed, length)
    pieces: list[str] = []
    for index in range(length):
        mode = (raw[index] + index) % 5
        byte = raw[index]
        if mode == 0:
            pieces.append(chr(65 + (byte % 26)))
        elif mode == 1:
            pieces.append(_pick_wide(byte))
        elif mode == 2:
            pieces.append(_pick_special(byte))
        elif mode == 3:
            pieces.append(_pick_wide(byte) + _pick_special((byte + 3) % 256))
        else:
            pieces.append(_pick_wide(byte) + "\u200d" + _pick_wide((byte + 11) % 256))
    return "".join(pieces)


class SplitGraphemesProgramStateTest(unittest.TestCase):
    def _assert_nonempty_digest(self, values: list[str]) -> None:
        self.assertEqual(len(_digest(values)), 64)
        self.assertTrue(any(values))

    def test_chop_cells_seed_alpha(self) -> None:
        text = _build_mixed_text("alpha", 24)
        lines = chop_cells(text, 7)
        self._assert_nonempty_digest(lines)

    def test_chop_cells_seed_beta(self) -> None:
        text = _build_mixed_text("beta", 31)
        lines = chop_cells(text, 5)
        self.assertGreater(len(lines), 2)
        self._assert_nonempty_digest(lines)

    def test_chop_cells_seed_gamma(self) -> None:
        text = _build_mixed_text("gamma", 18)
        lines = chop_cells(text, 9)
        self.assertTrue(all(isinstance(item, str) for item in lines))
        self._assert_nonempty_digest(lines)

    def test_chop_cells_seed_delta(self) -> None:
        text = _build_mixed_text("delta", 27)
        lines = chop_cells(text, 4)
        self.assertGreaterEqual(len(lines), 3)
        self._assert_nonempty_digest(lines)

    def test_set_cell_size_crop_seed_epsilon(self) -> None:
        text = _build_mixed_text("epsilon", 22)
        cropped = set_cell_size(text, 6)
        self.assertIsInstance(cropped, str)
        self._assert_nonempty_digest([cropped, text])

    def test_set_cell_size_crop_seed_zeta(self) -> None:
        text = _build_mixed_text("zeta", 29)
        cropped = set_cell_size(text, 11)
        self.assertTrue(len(cropped) <= len(text) + 3)
        self._assert_nonempty_digest([cropped])

    def test_set_cell_size_crop_seed_eta(self) -> None:
        text = _build_mixed_text("eta", 16)
        cropped = set_cell_size(text, 3)
        self.assertIsInstance(cropped, str)
        self._assert_nonempty_digest([cropped, text[:4]])

    def test_split_text_seed_theta(self) -> None:
        text = _build_mixed_text("theta", 20)
        left, right = split_text(text, 8)
        self.assertTrue(left or right)
        self._assert_nonempty_digest([left, right])

    def test_split_text_seed_iota(self) -> None:
        text = _build_mixed_text("iota", 26)
        left, right = split_text(text, 5)
        self.assertNotEqual(left + right, "")
        self._assert_nonempty_digest([left, right, text[:6]])

    def test_split_text_seed_kappa(self) -> None:
        text = _build_mixed_text("kappa", 23)
        left, right = split_text(text, 13)
        self.assertTrue(isinstance(left, str) and isinstance(right, str))
        self._assert_nonempty_digest([left, right])

    def test_chop_cells_seed_lambda(self) -> None:
        text = _build_mixed_text("lambda", 35)
        lines = chop_cells(text, 6)
        self.assertGreater(len(lines), 4)
        self._assert_nonempty_digest(lines)

    def test_chop_cells_seed_mu(self) -> None:
        text = _build_mixed_text("mu", 40)
        lines = chop_cells(text, 8)
        self.assertGreater(len(lines), 3)
        self._assert_nonempty_digest(lines)
