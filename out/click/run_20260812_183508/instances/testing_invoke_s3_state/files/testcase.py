import os
import random
import unittest

import click
from click.testing import CliRunner


@click.command()
@click.option("--mode", type=click.Choice(("fold", "burst")))
@click.argument("values", nargs=-1, type=int)
def workload(mode, values):
    accumulator = 0
    transformed = []

    for index, value in enumerate(values):
        accumulator = (
            accumulator * (index % 5 + 3) + value * (index + 7)
        ) % 10007
        item = (accumulator ^ (value << (index % 3))) % 997
        transformed.append(item)
        click.echo(
            f"{index:02x}:{item:03x}:{accumulator:04x}",
            err=(item + index) % 4 == 0,
        )

        if index % 7 == 3:
            os.write(1, f"O{(item * 3 + index) % 251:02x}|".encode())
        elif index % 7 == 5:
            os.write(2, f"E{(accumulator + item) % 239:02x}|".encode())

    if mode == "burst":
        marker = sum((index + 1) * item for index, item in enumerate(transformed))
        raise RuntimeError(f"burst-{marker % 4093:x}")

    return (
        accumulator,
        tuple(transformed[::3]),
        sum(transformed) % 65521,
        sum(left < right for left, right in zip(transformed, transformed[1:])),
    )


def generated_values(seed, size):
    rng = random.Random(seed)
    state = rng.randrange(1000, 9000)
    values = []
    for index in range(size):
        state = (state * 73 + rng.randrange(17, 311) + index * index) % 7919
        values.append(state % 883 + 11)
    return values


class TestInvokeProgramState(unittest.TestCase):
    def test_seeded_multi_path_invocations(self):
        runner = CliRunner(capture="fd")

        warmup = generated_values(38177, 19)
        first = runner.invoke(
            workload,
            ["--mode", "fold", *(str(value) for value in warmup)],
            standalone_mode=False,
        )

        rejected = runner.invoke(
            workload,
            ["--not-an-option", str(sum(warmup) % 97)],
        )

        unstable = generated_values(92531, 21)
        caught = runner.invoke(
            workload,
            ["--mode", "burst", *(str(value) for value in unstable)],
        )

        final_values = generated_values(61403, 23)
        command_line = " ".join(
            ["--mode", "fold", *(str(value) for value in final_values)]
        )
        final = runner.invoke(
            workload,
            command_line,
            standalone_mode=False,
            color=(sum(final_values) % 2 == 0),
        )

        self.assertEqual(first.exit_code, 0)
        self.assertGreater(rejected.exit_code, 0)
        self.assertIsNotNone(caught.exception)
        self.assertEqual(final.exit_code, 0)
        self.assertIsInstance(final.return_value, tuple)
        self.assertEqual(len(final.return_value[1]), (len(final_values) + 2) // 3)
        self.assertGreater(final.stdout.count("\n"), len(final_values) // 2)
        self.assertGreater(final.stderr.count("\n"), 0)
        self.assertEqual(len(final.output), len(final.stdout) + len(final.stderr))
