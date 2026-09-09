import io
import os
import unittest
from unittest.mock import patch

import click
import click._termui_impl as termui_impl


class StatefulPagerProcess:
    instances = []

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.environment = kwargs["env"]
        self.stdin = io.StringIO()
        self.wait_calls = 0
        self.interruptions = [
            (index * index + 3 * index + 7) % 11
            for index in range(len(argv) * 3 + 3)
        ]
        type(self).instances.append(self)

    def terminate(self):
        self.environment["TERMINATED"] = str(self.wait_calls)

    def wait(self):
        self.wait_calls += 1
        prior = int(self.environment["PULSE"])
        token = self.argv[self.wait_calls % len(self.argv)]
        mixed = (
            prior * 37
            + self.wait_calls * self.wait_calls
            + sum(ord(character) for character in token)
            + self.interruptions[(self.wait_calls - 1) % len(self.interruptions)]
        ) % 9973
        self.environment["PULSE"] = str(mixed)
        self.environment["WINDOW"] = "-".join(
            str((mixed >> shift) & 15) for shift in range(0, 12, 4)
        )
        if self.wait_calls <= len(self.interruptions):
            raise KeyboardInterrupt
        return mixed % len(self.argv)


class TestPipePagerState(unittest.TestCase):
    def test_generated_pager_wait_state(self):
        StatefulPagerProcess.instances.clear()
        pager_parts = ["less"] + [
            f"--opt{(index * 3 + 1) % 10}={((index + 2) * (index + 13)) % 37}"
            for index in range(3)
        ]
        controlled_environment = {
            f"CFG_{index}": chr(65 + ((index * 11 + 7) % 26))
            for index in range(22)
        }
        controlled_environment.update(
            {
                "PAGER": " ".join(pager_parts),
                "LESS": "".join(
                    chr(97 + ((index * 13 + 7) % 26)) for index in range(28)
                ),
                "PULSE": str(sum(ord(character) for character in pager_parts[0])),
                "WINDOW": "pending",
            }
        )

        with (
            patch.dict(os.environ, controlled_environment, clear=True),
            patch.object(termui_impl, "isatty", return_value=True),
            patch(
                "shutil.which",
                return_value="/virtual/deep/pager/toolchains/bin/less",
            ),
            patch("subprocess.Popen", StatefulPagerProcess),
        ):
            with click.get_pager_file() as pager:
                payload = "".join(
                    chr(97 + ((index * 7 + 11) % 26)) for index in range(97)
                )
                pager.write(payload)

        self.assertEqual(len(StatefulPagerProcess.instances), 1)
        process = StatefulPagerProcess.instances[0]
        self.assertGreater(process.wait_calls, len(pager_parts) * 3)
        self.assertTrue(process.stdin.closed)
