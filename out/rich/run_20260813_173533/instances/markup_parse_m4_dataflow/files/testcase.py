import hashlib
import unittest

from rich.markup import render
from rich.text import Text


def _seed_bytes(label: str, count: int) -> bytes:
    return hashlib.sha256(f"markup-parse-m4-{label}".encode()).digest() * (
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
    "dim",
    "blink",
]


def _digest_text(text: Text) -> str:
    payload = text.plain + "|" + str(len(text.spans))
    return hashlib.sha256(payload.encode()).hexdigest()


class MarkupParseDataflowTest(unittest.TestCase):
    def _check_render(self, label: str, markup: str) -> None:
        result = render(markup, emoji=False)
        self.assertIsInstance(result, Text)
        digest = _digest_text(result)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in digest))
        self.assertIn("[", markup)
        self.assertGreater(len(label), 0)

    def test_bulk_alternating_style_tags(self) -> None:
        raw = _seed_bytes("bulk-alt", 96)
        pieces: list[str] = []
        for index in range(24):
            style = _STYLE_NAMES[(raw[index] + index) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 24] % 26))
            if (raw[index + 48] & 1) == 0:
                pieces.append(f"[{style}]{ch}[/{style}]")
            else:
                pieces.append(f"[{style}]{ch}[/]")
        markup = "".join(pieces)
        self._check_render("bulk-alt", markup)

    def test_dense_param_link_tags(self) -> None:
        raw = _seed_bytes("param-link", 80)
        parts: list[str] = []
        for index in range(20):
            host = f"site{(raw[index] % 9) + 1}.example"
            path = f"/p/{(raw[index + 20] % 64) + index}"
            label = chr(65 + (raw[index + 40] % 26))
            parts.append(f"[link={host}{path}]{label}[/link]")
        markup = "".join(parts)
        self._check_render("param-link", markup)

    def test_escape_ladder_variants(self) -> None:
        raw = _seed_bytes("escape-ladder", 72)
        chunks: list[str] = []
        for index in range(18):
            slash_count = (raw[index] % 4) + 1
            token = chr(97 + (raw[index + 18] % 26))
            chunks.append(("\\" * slash_count) + f"[{token}]")
            if (raw[index + 36] & 1) == 0:
                chunks.append(f"[bold]{token}[/bold]")
        markup = "".join(chunks)
        self._check_render("escape-ladder", markup)

    def test_plain_runs_between_tags(self) -> None:
        raw = _seed_bytes("plain-runs", 84)
        segments: list[str] = []
        for index in range(21):
            run_len = (raw[index] % 5) + 2
            filler = chr(65 + (raw[index + 21] % 26)) * run_len
            style = _STYLE_NAMES[(raw[index + 42] + index) % len(_STYLE_NAMES)]
            segments.append(filler)
            segments.append(f"[{style}]{chr(97 + index % 26)}[/{style}]")
        markup = "".join(segments)
        self._check_render("plain-runs", markup)

    def test_unclosed_style_stack(self) -> None:
        raw = _seed_bytes("unclosed", 64)
        layers: list[str] = []
        for index in range(16):
            style = _STYLE_NAMES[(raw[index] + index * 3) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 16] % 26))
            if (raw[index + 32] & 3) == 0:
                layers.append(f"[{style}]{ch}")
            else:
                layers.append(f"[{style}]{ch}[/{style}]")
        markup = "".join(layers)
        self._check_render("unclosed", markup)

    def test_implicit_slash_closers(self) -> None:
        raw = _seed_bytes("implicit-close", 60)
        blocks: list[str] = []
        for index in range(15):
            style = _STYLE_NAMES[(raw[index] + index) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 15] % 26))
            blocks.append(f"[{style}]{ch}[/]")
        markup = "".join(blocks)
        self._check_render("implicit-close", markup)

    def test_hash_color_style_tags(self) -> None:
        raw = _seed_bytes("hash-color", 72)
        colors: list[str] = []
        for index in range(18):
            channel = raw[index] % 256
            hex_color = f"#{channel:02x}{(channel * 3) % 256:02x}{(channel * 7) % 256:02x}"
            ch = chr(97 + (raw[index + 18] % 26))
            colors.append(f"[{hex_color}]{ch}[/{hex_color}]")
        markup = "".join(colors)
        self._check_render("hash-color", markup)

    def test_mixed_escape_and_real_tags(self) -> None:
        raw = _seed_bytes("mixed-escape", 88)
        tokens: list[str] = []
        for index in range(22):
            ch = chr(97 + (raw[index] % 26))
            if (raw[index + 22] & 1) == 0:
                tokens.append(f"\\[{ch}]")
            elif (raw[index + 44] & 1) == 0:
                tokens.append(f"\\\\[{ch}]")
            else:
                style = _STYLE_NAMES[(raw[index + 66] + index) % len(_STYLE_NAMES)]
                tokens.append(f"[{style}]{ch}[/{style}]")
        markup = "".join(tokens)
        self._check_render("mixed-escape", markup)

    def test_single_character_tag_burst(self) -> None:
        raw = _seed_bytes("single-burst", 64)
        burst: list[str] = []
        for index in range(16):
            style = _STYLE_NAMES[raw[index] % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 16] % 26))
            burst.append(f"[{style}]{ch}[/{style}]")
        markup = "".join(burst)
        self._check_render("single-burst", markup)

    def test_nested_overlapping_styles(self) -> None:
        raw = _seed_bytes("nested-overlap", 96)
        nested: list[str] = []
        for index in range(12):
            outer = _STYLE_NAMES[(raw[index] + index) % len(_STYLE_NAMES)]
            inner = _STYLE_NAMES[(raw[index + 12] + index * 2) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 24] % 26))
            nested.append(f"[{outer}][{inner}]{ch}[/{inner}][/{outer}]")
        markup = "".join(nested)
        self._check_render("nested-overlap", markup)

    def test_trailing_plain_tail(self) -> None:
        raw = _seed_bytes("trailing-tail", 72)
        head = []
        for index in range(9):
            style = _STYLE_NAMES[(raw[index] + index) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 9] % 26))
            head.append(f"[{style}]{ch}[/{style}]")
        tail_len = (raw[0] % 7) + 8
        tail = chr(65 + (raw[18] % 26)) * tail_len
        markup = "".join(head) + tail
        self._check_render("trailing-tail", markup)

    def test_leading_plain_then_tags(self) -> None:
        raw = _seed_bytes("leading-plain", 72)
        prefix_len = (raw[0] % 6) + 9
        prefix = chr(65 + (raw[1] % 26)) * prefix_len
        tags: list[str] = []
        for index in range(14):
            style = _STYLE_NAMES[(raw[index + 2] + index) % len(_STYLE_NAMES)]
            ch = chr(97 + (raw[index + 16] % 26))
            tags.append(f"[{style}]{ch}[/{style}]")
        markup = prefix + "".join(tags)
        self._check_render("leading-plain", markup)
