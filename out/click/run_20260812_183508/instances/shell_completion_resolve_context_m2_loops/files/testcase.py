import random
import unittest

import click
from click.shell_completion import ShellComplete


class _SyntheticComplete(ShellComplete):
    name = "synthetic"
    source_template = ""

    def __init__(self, cli: click.Command, args: list[str], incomplete: str) -> None:
        super().__init__(cli, {}, "generated-cli", "_GENERATED_COMPLETE")
        self._args = args
        self._incomplete = incomplete

    def get_completion_args(self) -> tuple[list[str], str]:
        return self._args.copy(), self._incomplete

    def format_completion(self, item: click.shell_completion.CompletionItem) -> str:
        return f"{item.type}:{item.value}"


class ResolveContextLoopScenarios(unittest.TestCase):
    def _exercise(self, seed: int, rounds: int, style: str) -> None:
        rng = random.Random(seed * seed + rounds * 17)
        pool_size = 67 + rng.randrange(9)
        names = [f"unit-{index:x}-{rng.randrange(1 << 15):04x}" for index in range(pool_size)]
        cli = click.Group(
            "generated-cli",
            chain=True,
            commands=[click.Command(name) for name in names],
        )

        draws = [rng.randrange(pool_size) for _ in range(rounds * 3 + 5)]
        width = min(pool_size, 17 + sum(value % 5 for value in draws[:rounds]))
        args = rng.sample(names, width)

        if style == "early":
            pivot = (sum(draws[-rounds:]) + seed) % len(args)
            args.insert(pivot, f"missing-{rng.randrange(1 << 20):x}")
        elif style == "empty":
            args.clear()
        elif style == "rotate":
            shift = (draws[-1] + rounds) % len(args)
            args = args[shift:] + args[:shift]
        elif style == "repeat":
            args.insert(len(args) // 3, args[(draws[0] + seed) % len(args)])

        incomplete = names[draws[-1]][: 2 + draws[-2] % 5]
        output = _SyntheticComplete(cli, args, incomplete).complete()

        self.assertIsInstance(output, str)
        self.assertNotIn("\x00", output)

    def test_valid_short_generated_chain(self) -> None:
        self._exercise(1, 4, "valid")

    def test_valid_medium_generated_chain(self) -> None:
        self._exercise(2, 6, "valid")

    def test_valid_long_generated_chain(self) -> None:
        self._exercise(3, 9, "valid")

    def test_rotated_generated_chain(self) -> None:
        self._exercise(4, 7, "rotate")

    def test_second_rotated_generated_chain(self) -> None:
        self._exercise(5, 8, "rotate")

    def test_repeated_command_chain(self) -> None:
        self._exercise(6, 5, "repeat")

    def test_late_unknown_command(self) -> None:
        self._exercise(7, 4, "early")

    def test_data_positioned_unknown_command(self) -> None:
        self._exercise(8, 7, "early")

    def test_unknown_in_larger_chain(self) -> None:
        self._exercise(9, 9, "early")

    def test_empty_generated_chain(self) -> None:
        self._exercise(3, 5, "empty")

    def test_alternate_valid_chain(self) -> None:
        self._exercise(5, 6, "valid")

    def test_alternate_repeated_chain(self) -> None:
        self._exercise(7, 8, "repeat")
