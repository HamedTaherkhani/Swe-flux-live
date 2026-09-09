import os
import unittest
from unittest import mock

import click
from click.testing import CliRunner


class TestIsolationLoopBehavior(unittest.TestCase):
    def test_generated_environment_round_trip(self):
        def build_environment(seed, count, label, deletion_modulus):
            state = seed
            environment = {}
            for ordinal in range(count):
                state = (state * 73 + 41) % 997
                key_number = (
                    state * state + ordinal * 29 + seed * 11
                ) % 89
                key = f"REPOBEHAVE_DYNAMIC_{key_number:03d}"
                if (state + ordinal) % deletion_modulus == 0:
                    environment[key] = None
                else:
                    environment[key] = (
                        f"{label}-{state ^ (ordinal * deletion_modulus)}"
                    )
            return environment

        runner_environment = build_environment(137, 47, "base", 5)
        invocation_environment = build_environment(
            281, 43, "override", 7
        )
        expected_environment = {
            **runner_environment,
            **invocation_environment,
        }
        preexisting_environment = {
            key: f"preexisting-{position * position + 1}"
            for position, key in enumerate(sorted(expected_environment))
            if (sum(map(ord, key)) + position) % 4 == 0
        }

        @click.command()
        def inspect_environment():
            observed = {
                key: os.environ.get(key)
                for key in sorted(expected_environment)
            }
            return observed == expected_environment

        with mock.patch.dict(
            os.environ, preexisting_environment, clear=False
        ):
            result = CliRunner(env=runner_environment).invoke(
                inspect_environment,
                env=invocation_environment,
                standalone_mode=False,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(result.exception)
        self.assertIs(result.return_value, True)
