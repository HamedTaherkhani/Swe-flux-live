from __future__ import annotations

import random
import unittest

import click
from click.testing import CliRunner


class GeneratedKindOption(click.Option):
    pass


class TestMissingParameterDataFlow(unittest.TestCase):
    def test_seeded_missing_parameter_matrix(self) -> None:
        rng = random.Random(1618033988)
        modes = list(range(8)) * 15
        rng.shuffle(modes)
        runner = CliRunner()
        results = []

        for index, mode in enumerate(modes):
            stem = "".join(
                rng.choice("abcdefghjkmnpqrstuvwxyz")
                for _ in range(3 + index % 13)
            )

            if mode == 0:
                use_tuple = index % 5 == 4
                parameter = click.Argument(
                    [f"{stem}_{index:04x}"],
                    type=click.Choice(
                        [
                            f"{stem}{chr(97 + offset)}"
                            for offset in range(1 + index % 8)
                        ],
                        case_sensitive=index % 4 != 0,
                    )
                    if not use_tuple
                    else click.Tuple(
                        [click.STRING, click.IntRange(0, 50 + index % 100)]
                    ),
                    nargs=2 if use_tuple else 1,
                    required=True,
                )
            elif mode == 1:
                parameter = click.Option(
                    [f"--{stem}-{index:04x}", f"-{chr(106 + index % 20)}"],
                    envvar=[f"{stem.upper()}_{index:04x}", f"ALT_{index:03x}"]
                    if index % 6 < 2
                    else f"{stem.upper()}_{index:04x}"
                    if index % 6 < 4
                    else None,
                    show_envvar=index % 6 < 4,
                    type=click.Path()
                    if index % 8 == 0
                    else click.FLOAT
                    if index % 8 == 1
                    else None,
                    required=True,
                )
            elif mode == 2:
                choices = [
                    f"{stem}{chr(97 + offset)}"
                    for offset in range(2 + index % 10)
                ]
                parameter = click.Option(
                    [f"--{stem}-{index:04x}", f"-{chr(107 + (index + len(stem)) % 19)}"],
                    type=click.Choice(choices, case_sensitive=index % 3 == 0)
                    if index % 4 != 3
                    else click.IntRange(-20 + index % 10, 80 + index % 50),
                    show_choices=index % 5 != 0,
                    required=True,
                )
            else:
                parameter = GeneratedKindOption(
                    [f"--{stem}-{index:04x}", f"-{chr(108 + (index + mode) % 18)}"],
                    required=True,
                )
                if mode == 3:
                    parameter.param_type_name = "parameter"
                elif mode == 4:
                    parameter.param_type_name = "option"
                elif mode == 5:
                    parameter.param_type_name = "argument"
                else:
                    parameter.param_type_name = (
                        f"channel-{(index * 17 + mode * 3):05x}-{stem[:5]}"
                    )

            command = click.Command(
                f"task-{index:05x}-{stem[:4]}",
                params=[parameter],
                callback=lambda **values: click.echo(len(values)),
            )
            results.append(runner.invoke(command, []))

        self.assertEqual(len(results), len(modes))
        self.assertTrue(all(result.exit_code == 2 for result in results))
        self.assertTrue(all(result.exception is not None for result in results))
        self.assertGreater(len({len(result.output) for result in results}), 3)
