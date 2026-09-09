import hashlib
import unittest

from rich.text import Text


def _build_payload(seed: int) -> str:
    rng_state = hashlib.sha256(f"ansi-cfg-{seed}".encode()).digest()
    lines = []
    for i in range(24):
        byte = rng_state[i % len(rng_state)]
        kind = byte % 7
        tag = f"L{i:02d}"
        if kind == 0:
            lines.append(f"{tag}-plain")
        elif kind == 1:
            lines.append(f"\x1b[1m{tag}-bold\x1b[0m")
        elif kind == 2:
            lines.append(f"\x1b[38;5;{byte % 256}m{tag}-fg256\x1b[0m")
        elif kind == 3:
            r, g, b = byte, rng_state[(i + 1) % len(rng_state)], rng_state[(i + 3) % len(rng_state)]
            lines.append(f"\x1b[38;2;{r};{g};{b}m{tag}-fgtrue\x1b[0m")
        elif kind == 4:
            lines.append(f"\x1b[48;5;{byte % 256}m{tag}-bg256\x1b[0m")
        elif kind == 5:
            r, g, b = byte, rng_state[(i + 2) % len(rng_state)], rng_state[(i + 5) % len(rng_state)]
            lines.append(f"\x1b[48;2;{r};{g};{b}m{tag}-bgtrue\x1b[0m")
        else:
            lines.append(f"\x1b]8;;https://ex/{tag}\x07{tag}-link\x1b]8;;\x07")
    return "\n".join(lines) + "\n"


class AnsiDecodeLineCfgTest(unittest.TestCase):
    def test_seeded_multiline_ansi_decode(self) -> None:
        payload = _build_payload(17)
        result = Text.from_ansi(payload)
        self.assertGreater(len(result.plain), 0)
        self.assertIn("L00", result.plain)
        digest = hashlib.md5(result.plain.encode()).hexdigest()
        self.assertEqual(len(digest), 32)
