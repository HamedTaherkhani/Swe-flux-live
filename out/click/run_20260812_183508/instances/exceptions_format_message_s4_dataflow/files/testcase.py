from __future__ import annotations

import random
import unittest

import click
from click.testing import CliRunner


class GeneratedKindOption(click.Option):
    pass


class TestMissingParameterDataFlow(unittest.TestCase):
    def test_seeded_missing_parameter_matrix(self) -> None:
        rng = random.Random(8675309)
        modes = list(range(5)) * 5
        rng.shuffle(modes)
        runner = CliRunner()
        results = []

        for index, mode in enumerate(modes):
            stem = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(7))

            if mode == 0:
                parameter = click.Argument(
                    [f"{stem}_{index:x}"],
                    required=True,
                )
            elif mode == 1:
                parameter = click.Option(
                    [f"--{stem}-{index:x}"],
                    required=True,
                )
            elif mode == 2:
                choices = [
                    f"{stem}{chr(97 + offset)}"
                    for offset in range(2 + index % 4)
                ]
                parameter = click.Option(
                    [f"--{stem}-{index:x}"],
                    type=click.Choice(choices),
                    required=True,
                )
            else:
                parameter = GeneratedKindOption(
                    [f"--{stem}-{index:x}"],
                    required=True,
                )
                if mode == 3:
                    parameter.param_type_name = "parameter"
                else:
                    parameter.param_type_name = f"channel-{(index * 7 + 3):x}"

            command = click.Command(
                f"task-{index:x}",
                params=[parameter],
                callback=lambda **values: click.echo(len(values)),
            )
            results.append(runner.invoke(command, []))

        self.assertEqual(len(results), len(modes))
        self.assertTrue(all(result.exit_code == 2 for result in results))
        self.assertTrue(all(result.exception is not None for result in results))
        self.assertGreater(len({len(result.output) for result in results}), 3)
