import unittest

import click
from click.testing import CliRunner


class TestGeneratedPathConversions(unittest.TestCase):
    def test_generated_command_arguments(self):
        runner = CliRunner()
        outcomes = []
        converted = []
        state = 47

        for index in range(168):
            state = (state * 43 + index * 29 + 31) % 1021
            selector = (state ^ (state >> 3) ^ index) % 7
            path_type = bytes if (index * 7 + selector) % 3 == 0 else str

            if selector == 0:
                settings = {
                    "exists": False,
                    "path_type": path_type,
                    "resolve_path": index % 3 != 1,
                }
                candidate = (
                    f"vault_{(index * 31 + 13) % 149}/"
                    f"tier_{(index * index * 5 + 19) % 103}/"
                    f"node_{(index * 11 + selector * 3) % 79}"
                )
            elif selector == 1:
                settings = {
                    "exists": True,
                    "path_type": path_type,
                    "writable": True,
                }
                candidate = "src/click/core.py"
            elif selector == 2:
                settings = {
                    "exists": True,
                    "file_okay": False,
                    "path_type": path_type,
                }
                candidate = "src/click/core.py"
            elif selector == 3:
                settings = {
                    "exists": True,
                    "dir_okay": False,
                    "path_type": path_type,
                }
                candidate = "missing_dir_probe_77/absent"
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
                candidate = "src/click/../../src/click/./core.py"
            else:
                settings = {
                    "exists": True,
                    "executable": True,
                    "path_type": path_type,
                }
                candidate = "src/click/core.py"

            argument_type = click.Path(**settings)

            @click.command()
            @click.argument("candidate", type=argument_type)
            def command(candidate):
                converted.append(candidate)

            result = runner.invoke(command, [candidate])
            should_fail = selector in {2, 3, 6}
            outcomes.append(result.exit_code != 0)
            self.assertEqual(result.exit_code != 0, should_fail)

        self.assertEqual(len(outcomes), 168)
        self.assertGreater(sum(outcomes), 55)
        self.assertEqual(len(converted), len(outcomes) - sum(outcomes))