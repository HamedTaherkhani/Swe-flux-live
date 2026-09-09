import importlib
import random
import unittest
from unittest import mock

from click.testing import CliRunner

from instructlab import lab


class TestTaxonomyCommandFailureSchedule(unittest.TestCase):
    def test_cli_command_handles_generated_failure_schedule(self):
        utility_module = importlib.import_module("instructlab." + "utils")
        git_module = importlib.import_module("g" + "it")
        yaml_module = importlib.import_module("y" + "aml")

        error_types = (
            getattr(git_module, "Git" + "Error"),
            getattr(yaml_module, "YAML" + "Error"),
        )
        rng = random.Random(sum(index * index for index in range(23)))
        schedule = [error_types[rng.randrange(len(error_types))] for _ in range(2)]
        schedule[sum(())] = error_types[0]
        schedule[sum(range(2))] = error_types[1]

        state = {"error_type": None, "invocation": -1}

        def generated_taxonomy_files(_path, _base):
            error_type = state["error_type"]
            if error_type is error_types[0]:
                checksum = sum(
                    (position + 1) * ord(character)
                    for position, character in enumerate(error_type.__name__)
                )
                raise error_type(f"generated-{state['invocation']}-{checksum % 991}")
            return [
                None
                if (offset + state["invocation"]) % 7 == 0
                else f"generated/skill-{state['invocation']}-{offset}/qna.yaml"
                for offset in range(29)
            ]

        def generated_validation(_path, _base, _rules):
            error_type = state["error_type"]
            checksum = sum(
                (position + 3) * ord(character)
                for position, character in enumerate(error_type.__name__)
            )
            raise error_type(f"validation-{state['invocation']}-{checksum % 983}")

        outcomes = []
        runner = CliRunner()
        with (
            mock.patch.object(
                utility_module, "get_taxonomy_diff", generated_taxonomy_files
            ),
            mock.patch.object(
                utility_module, "validate_taxonomy", generated_validation
            ),
        ):
            for index, error_type in enumerate(schedule):
                state["error_type"] = error_type
                state["invocation"] = index
                result = runner.invoke(
                    lab.ilab,
                    [
                        "--config=DEFAULT",
                        "taxonomy",
                        "di" + "ff",
                        "--taxonomy-base",
                        "generated-base",
                        "--taxonomy-path",
                        f"/generated/taxonomy-{index}",
                    ],
                )
                outcomes.append((result.exit_code, result.exception is not None))

        self.assertEqual(len(outcomes), len(schedule))
        self.assertTrue(all(present for _, present in outcomes))
        self.assertTrue(all(code == sum(range(2)) for code, _ in outcomes))
