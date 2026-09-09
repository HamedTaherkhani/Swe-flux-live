"""Direct exercise of Color.downgrade across varied color-system targets."""

import random
import unittest

from rich.color import Color, ColorSystem, ColorType


def _build_downgrade_batch(seed: int, count: int) -> list[tuple[Color, ColorSystem]]:
    """Build deterministic (color, target_system) pairs for downgrade calls."""
    rng = random.Random(seed)
    batch: list[tuple[Color, ColorSystem]] = []
    for index in range(count):
        branch = index % 7
        tag = f"slot{index:02d}"
        if branch == 0:
            red = rng.randint(0, 255)
            green = rng.randint(0, 255)
            blue = rng.randint(0, 255)
            color = Color.from_rgb(red, green, blue)._replace(name=f"tc-{tag}")
            target = ColorSystem.TRUECOLOR
        elif branch == 1:
            color = Color.default()._replace(name=f"def-{tag}")
            target = ColorSystem.EIGHT_BIT
        elif branch == 2:
            level = rng.randint(0, 255)
            color = Color.from_rgb(level, level, level)._replace(name=f"gs-{tag}")
            target = ColorSystem.EIGHT_BIT
        elif branch == 3:
            red = rng.randint(50, 255)
            green = rng.randint(50, 255)
            blue = rng.randint(50, 255)
            color = Color.from_rgb(red, green, blue)._replace(name=f"eb-{tag}")
            target = ColorSystem.EIGHT_BIT
        elif branch == 4:
            red = rng.randint(0, 255)
            green = rng.randint(0, 255)
            blue = rng.randint(0, 255)
            color = Color.from_rgb(red, green, blue)._replace(name=f"st-{tag}")
            target = ColorSystem.STANDARD
        elif branch == 5:
            number = rng.randint(16, 255)
            color = Color.from_ansi(number)._replace(name=f"an-{number}-{tag}")
            target = ColorSystem.STANDARD
        else:
            number = rng.randint(0, 255)
            color = Color.from_ansi(number)._replace(name=f"wn-{number}-{tag}")
            target = ColorSystem.WINDOWS
        batch.append((color, target))
    return batch


class TestColorDowngradeCFG(unittest.TestCase):
    def test_direct_downgrade_batch(self) -> None:
        batch = _build_downgrade_batch(seed=0xC0DECAFE, count=35)
        results: list[Color] = []
        type_codes: list[int] = []

        for color, target in batch:
            downgraded = color.downgrade(target)
            results.append(downgraded)
            type_codes.append(int(downgraded.type))

        self.assertEqual(len(results), len(batch))
        self.assertTrue(all(isinstance(item, Color) for item in results))
        self.assertGreater(len(set(type_codes)), 3)
        self.assertGreater(sum(type_codes), 0)
        self.assertIn(int(ColorType.EIGHT_BIT), type_codes)
        self.assertIn(int(ColorType.STANDARD), type_codes)
        self.assertIn(int(ColorType.WINDOWS), type_codes)
        self.assertGreater(len({item.name for item in results}), 20)
