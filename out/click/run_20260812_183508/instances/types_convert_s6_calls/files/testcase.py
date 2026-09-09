import unittest

import click
from click.testing import CliRunner


class TestGeneratedPathConversions(unittest.TestCase):
    def test_generated_command_arguments(self):
        runner = CliRunner()
        outcomes = []
        converted = []
        state = 19

        for index in range(42):
            state = (state * 37 + index * 13 + 17) % 997
            selector = (state ^ (state >> 3) ^ index) % 7
            path_type = bytes if (index * 3 + selector) % 4 == 0 else str

            if selector == 0:
                settings = {
                    "exists": False,
                    "path_type": path_type,
                    "resolve_path": index % 2 == 0,
                }
                candidate = (
                    f"generated_{(index * 17 + 9) % 101}/"
                    f"item_{(index * index + 23) % 97}"
                )
            elif selector == 1:
                settings = {"exists": True, "path_type": path_type}
                candidate = "src/click/types.py"
            elif selector == 2:
                settings = {
                    "exists": True,
                    "file_okay": False,
                    "path_type": path_type,
                }
                candidate = "src/click/types.py"
            elif selector == 3:
                settings = {
                    "exists": True,
                    "dir_okay": False,
                    "path_type": path_type,
                }
                candidate = "src/click"
            elif selector == 4:
                settings = {
                    "exists": True,
                    "allow_dash": True,
                    "path_type": path_type,
                }
                candidate = "-"
            elif selector == 5:
                settings = {
                    "exists": True,
                    "resolve_path": True,
                    "path_type": path_type,
                }
                candidate = "src/click/../click/types.py"
            else:
                settings = {
                    "exists": True,
                    "executable": True,
                    "path_type": path_type,
                }
                candidate = "src/click/types.py"

            argument_type = click.Path(**settings)

            @click.command()
            @click.argument("candidate", type=argument_type)
            def command(candidate):
                converted.append(candidate)

            result = runner.invoke(command, [candidate])
            should_fail = selector in {2, 3, 6}
            outcomes.append(result.exit_code != 0)
            self.assertEqual(result.exit_code != 0, should_fail)

        self.assertEqual(len(outcomes), 42)
        self.assertGreater(sum(outcomes), 15)
        self.assertEqual(len(converted), len(outcomes) - sum(outcomes))
