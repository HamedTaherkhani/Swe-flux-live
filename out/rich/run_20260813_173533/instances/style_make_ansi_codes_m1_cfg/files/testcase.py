import hashlib
import io
import unittest
from contextlib import redirect_stdout

from rich.color import ColorSystem
from rich.style import Style


def _render_token(style: Style, token: str, color_system: ColorSystem) -> str:
    return style.render(token, color_system=color_system)


def _preview_token(style: Style, token: str) -> None:
    with redirect_stdout(io.StringIO()):
        style.test(token)


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("".join(parts).encode()).hexdigest()


class StyleMakeAnsiCodesM1CfgTest(unittest.TestCase):
    def test_primary_face_bits(self) -> None:
        specs = [
            {"bold": True},
            {"dim": True},
            {"italic": True},
            {"underline": True},
            {"bold": True, "dim": True, "italic": True, "underline": True},
        ]
        outputs: list[str] = []
        for index in range(18):
            spec = specs[index % len(specs)]
            style = Style(**spec)
            outputs.append(
                _render_token(style, f"p{index}", ColorSystem.TRUECOLOR)
            )
        self.assertTrue(all("\x1b[" in item for item in outputs))
        self.assertEqual(len(_digest(outputs)), 64)

    def test_motion_bits_loop(self) -> None:
        motion_sets = [
            {"blink": True},
            {"blink2": True},
            {"reverse": True},
            {"blink": True, "blink2": True, "reverse": True},
            {"blink": True, "conceal": True, "strike": True},
        ]
        outputs: list[str] = []
        for index in range(21):
            style = Style(**motion_sets[index % len(motion_sets)])
            outputs.append(
                _render_token(style, f"m{index}", ColorSystem.EIGHT_BIT)
            )
        self.assertGreater(len(outputs), 15)
        self.assertIn("\x1b[", outputs[-1])

    def test_conceal_and_strike_bits(self) -> None:
        outputs: list[str] = []
        for index in range(16):
            conceal = index % 3 == 0
            strike = index % 2 == 0
            style = Style(conceal=conceal, strike=strike)
            outputs.append(
                _render_token(style, f"c{index}", ColorSystem.STANDARD)
            )
        self.assertEqual(len(outputs), 16)
        self.assertTrue(any("5" in item or "9" in item for item in outputs))

    def test_decoration_high_bits(self) -> None:
        decorations = [
            {"underline2": True},
            {"frame": True},
            {"encircle": True},
            {"overline": True},
            {
                "underline2": True,
                "frame": True,
                "encircle": True,
                "overline": True,
            },
        ]
        outputs: list[str] = []
        for index in range(22):
            style = Style(**decorations[index % len(decorations)])
            outputs.append(
                _render_token(style, f"d{index}", ColorSystem.TRUECOLOR)
            )
        self.assertGreater(len(_digest(outputs)), 32)

    def test_named_foreground_colors(self) -> None:
        palette = [
            "red",
            "green",
            "blue",
            "yellow",
            "magenta",
            "cyan",
            "white",
            "black",
        ]
        outputs: list[str] = []
        for index in range(24):
            color = palette[index % len(palette)]
            style = Style(color=color)
            outputs.append(
                _render_token(style, f"f{index}", ColorSystem.STANDARD)
            )
        self.assertEqual(len(outputs), 24)
        self.assertTrue(all(item.endswith("\x1b[0m") for item in outputs))

    def test_rgb_foreground_downgrade(self) -> None:
        seed = hashlib.sha256(b"rgb-fg-downgrade").digest()
        outputs: list[str] = []
        for index in range(20):
            r = seed[index % len(seed)]
            g = seed[(index + 3) % len(seed)]
            b = seed[(index + 7) % len(seed)]
            style = Style(color=f"rgb({r},{g},{b})")
            system = ColorSystem.TRUECOLOR if index % 2 == 0 else ColorSystem.EIGHT_BIT
            outputs.append(_render_token(style, f"r{index}", system))
        self.assertGreater(len(outputs), 10)
        self.assertIn("\x1b[38", outputs[0])

    def test_background_only_styles(self) -> None:
        backgrounds = [
            "blue",
            "on red",
            "on rgb(12,34,56)",
            "on color(42)",
        ]
        outputs: list[str] = []
        for index in range(18):
            style = Style.parse(backgrounds[index % len(backgrounds)])
            outputs.append(
                _render_token(style, f"b{index}", ColorSystem.EIGHT_BIT)
            )
        self.assertEqual(len(outputs), 18)
        self.assertTrue(any("\x1b[48" in item for item in outputs))

    def test_combined_palette_render(self) -> None:
        combos = [
            "bold red",
            "italic on blue",
            "underline green on yellow",
            "blink2 magenta on cyan",
            "reverse white on black",
        ]
        outputs: list[str] = []
        for index in range(21):
            style = Style.parse(combos[index % len(combos)])
            system = (
                ColorSystem.TRUECOLOR
                if index % 3 == 0
                else ColorSystem.STANDARD
                if index % 3 == 1
                else ColorSystem.EIGHT_BIT
            )
            outputs.append(_render_token(style, f"x{index}", system))
        self.assertGreater(len(_digest(outputs)), 40)

    def test_windows_color_system(self) -> None:
        outputs: list[str] = []
        for index in range(14):
            style = Style(
                color=f"color({index % 16})",
                bgcolor=f"color({(index + 5) % 16})",
                bold=index % 2 == 0,
            )
            outputs.append(
                _render_token(style, f"w{index}", ColorSystem.WINDOWS)
            )
        self.assertEqual(len(outputs), 14)
        self.assertTrue(all("\x1b[" in item for item in outputs))

    def test_cached_style_short_circuit(self) -> None:
        style = Style.parse("bold cyan on black")
        outputs: list[str] = []
        for index in range(17):
            outputs.append(
                _render_token(style, f"k{index}", ColorSystem.TRUECOLOR)
            )
        self.assertEqual(len(outputs), 17)
        prefixes = [item[: item.index("m") + 1] for item in outputs]
        self.assertEqual(len(set(prefixes)), 1)

    def test_terminal_preview_chain(self) -> None:
        previews = [
            Style.parse("bold"),
            Style.parse("italic red"),
            Style.parse("underline on blue"),
            Style.parse("frame green"),
        ]
        for index in range(12):
            style = previews[index % len(previews)]
            _preview_token(style, f"t{index}")
        rendered = _render_token(previews[0], "check", ColorSystem.TRUECOLOR)
        self.assertIn("\x1b[", rendered)

    def test_seeded_programmatic_matrix(self) -> None:
        digest = hashlib.sha256(b"style-matrix-m1").digest()
        attr_names = [
            "bold",
            "dim",
            "italic",
            "underline",
            "blink",
            "blink2",
            "reverse",
            "conceal",
            "strike",
            "underline2",
            "frame",
            "encircle",
            "overline",
        ]
        outputs: list[str] = []
        for index in range(26):
            byte = digest[index % len(digest)]
            kwargs = {}
            for bit, name in enumerate(attr_names):
                if byte & (1 << (bit % 8)):
                    kwargs[name] = True
            if index % 4 == 0:
                kwargs["color"] = f"color({byte % 256})"
            if index % 5 == 0:
                kwargs["bgcolor"] = f"color({(byte + 17) % 256})"
            style = Style(**kwargs)
            system = [
                ColorSystem.STANDARD,
                ColorSystem.EIGHT_BIT,
                ColorSystem.TRUECOLOR,
                ColorSystem.WINDOWS,
            ][index % 4]
            outputs.append(_render_token(style, f"s{index}", system))
        self.assertEqual(len(outputs), 26)
        self.assertGreater(len(set(outputs)), 8)
