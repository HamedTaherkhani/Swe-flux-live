import hashlib
import unittest

from rich.markup import render
from rich.text import Text


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"markup-render-s2-{label}".encode()).digest() * (
        (count // 32) + 1
    )


_STYLE_NAMES = [
    "red",
    "green",
    "blue",
    "yellow",
    "magenta",
    "cyan",
    "bold",
    "italic",
    "underline",
    "reverse",
]


def _build_markup(segment_count: int) -> str:
    raw = _seed_bytes("omega", segment_count * 3)
    pieces: list[str] = []
    for index in range(segment_count):
        style = _STYLE_NAMES[(raw[index] + index) % len(_STYLE_NAMES)]
        character = chr(97 + (raw[index + segment_count] % 26))
        if (raw[index + 2 * segment_count] & 1) == 0:
            pieces.append(f"[{style}]{character}[/]")
        else:
            pieces.append(f"[{style}]{character}")
    return "".join(pieces)


def _digest_text(text: Text) -> str:
    payload = text.plain + "|" + str(len(text.spans))
    return hashlib.sha256(payload.encode()).hexdigest()


class MarkupRenderLoopsTest(unittest.TestCase):
    def test_seeded_render_loop_behavior(self) -> None:
        markup = _build_markup(30)
        result = render(markup, emoji=False)
        self.assertIsInstance(result, Text)
        self.assertEqual(len(result.plain), 30)
        self.assertGreater(len(result.spans), 0)
        digest = _digest_text(result)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))
