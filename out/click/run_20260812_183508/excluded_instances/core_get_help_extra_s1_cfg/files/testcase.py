import enum
import random
import unittest

import click
from click.testing import CliRunner


class Flavor(enum.Enum):
    VANILLA = "vanilla"
    CITRUS = "citrus"
    SPICE = "spice"


class TestGeneratedOptionHelp(unittest.TestCase):
    def test_seeded_option_matrix_help(self):
        rng = random.Random(87431)
        indices = list(range(24))
        rng.shuffle(indices)
        params = []

        for position, index in enumerate(indices):
            mode = index % 6
            common = {
                "help": f"generated setting {position * position + index}",
                "required": index % 7 == 0,
            }

            if mode == 0:
                params.append(
                    click.Option(
                        [f"--item-{index}"],
                        envvar=(
                            f"APP_ITEM_{index}",
                            f"LEGACY_ITEM_{index + position}",
                        ),
                        show_envvar=True,
                        default=(index - position, index + position),
                        show_default=True,
                        type=click.IntRange(-(index + 3), index * 2 + 5),
                        **common,
                    )
                )
            elif mode == 1:
                params.append(
                    click.Option(
                        [f"--item-{index}"],
                        show_envvar=True,
                        default=index * position + 1,
                        type=click.IntRange(index // 2, index * 3 + 9),
                        **common,
                    )
                )
            elif mode == 2:
                params.append(
                    click.Option(
                        [f"--feature-{index}/--no-feature-{index}"],
                        default=(position + index) % 3 != 0,
                        show_default=True,
                        **common,
                    )
                )
            elif mode == 3:
                params.append(
                    click.Option(
                        [f"--item-{index}"],
                        default=list(Flavor)[(position + index) % len(Flavor)],
                        show_default=True,
                        type=click.Choice(Flavor),
                        **common,
                    )
                )
            elif mode == 4:
                params.append(
                    click.Option(
                        [f"--item-{index}"],
                        default=lambda n=index, p=position: n * n - p,
                        show_default=True,
                        type=int,
                        **common,
                    )
                )
            else:
                params.append(
                    click.Option(
                        [f"--item-{index}"],
                        default="",
                        show_default=(position % 4 != 0),
                        type=str,
                        **common,
                    )
                )

        command = click.Command(
            "matrix",
            params=params,
            callback=lambda **values: values,
            context_settings={
                "auto_envvar_prefix": f"CFG_{sum(indices[::3])}",
                "show_default": True,
            },
        )
        result = CliRunner().invoke(command, ["--help"], env={})

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Options:", result.output)
        self.assertGreater(result.output.count("generated setting"), len(params) - 1)
