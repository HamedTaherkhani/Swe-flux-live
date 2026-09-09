import hashlib
import unittest

from rich.color import Color


def _digest(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"color-parse-s5-{seed}-{label}".encode()).digest()


def _build_color_specs(seed: int, count: int) -> list[str]:
    digest = _digest(seed, "specs")
    ansi_names = (
        "black",
        "red",
        "green",
        "yellow",
        "blue",
        "magenta",
        "cyan",
        "white",
        "bright_red",
        "bright_blue",
        "grey42",
        "gray50",
        "orange1",
        "purple4",
        "sky_blue1",
    )
    specs: list[str] = []
    for index in range(count):
        branch = (digest[index % len(digest)] + index * 5) % 7
        slot_a = digest[(index * 3 + 1) % len(digest)]
        slot_b = digest[(index * 5 + 7) % len(digest)]
        slot_c = digest[(index * 11 + 13) % len(digest)]
        if branch == 0:
            specs.append("default")
        elif branch == 1:
            specs.append(ansi_names[(slot_a + index) % len(ansi_names)])
        elif branch == 2:
            specs.append(f"#{slot_a:02x}{slot_b:02x}{slot_c:02x}")
        elif branch == 3:
            specs.append(f"color({slot_a % 16})")
        elif branch == 4:
            specs.append(f"color({16 + (slot_a % 240)})")
        elif branch == 5:
            specs.append(f"rgb({slot_a},{slot_b},{slot_c})")
        else:
            specs.append(f"  {ansi_names[slot_b % len(ansi_names)].upper()}  ")
    return specs


def _failure_slot(seed: int, count: int) -> int:
    digest = _digest(seed, "failure-slot")
    return 3 + (digest[0] % (count - 6))


def _failure_token(seed: int) -> str:
    digest = _digest(seed, "failure-token")
    overflow = 256 + (digest[1] % 180) + (digest[2] % 17)
    return f"color({overflow})"


def _result_fingerprint(colors: list[Color]) -> int:
    total = 0
    for parsed in colors:
        total += parsed.type.value
        if parsed.number is not None:
            total += parsed.number * 3
        if parsed.triplet is not None:
            total += parsed.triplet.red + parsed.triplet.green * 2 + parsed.triplet.blue * 5
    return total


class ColorParseExceptionsTest(unittest.TestCase):
    def test_seeded_parse_batch_with_single_propagated_error(self) -> None:
        seed = 5711
        batch_size = 28
        specs = _build_color_specs(seed, batch_size)
        fail_index = _failure_slot(seed, batch_size)
        specs[fail_index] = _failure_token(seed)

        parsed_colors: list[Color] = []
        for index, spec in enumerate(specs):
            if index == fail_index:
                with self.assertRaises(Exception):
                    Color.parse(spec)
                continue
            parsed_colors.append(Color.parse(spec))

        self.assertEqual(len(parsed_colors), batch_size - 1)
        self.assertGreater(len({item.type for item in parsed_colors}), 3)
        self.assertGreater(_result_fingerprint(parsed_colors), 5000)
