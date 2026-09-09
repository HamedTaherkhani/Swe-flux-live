from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

from kedro.framework.cli.starters import create_cli


def _generated_prompt_data() -> tuple[dict[str, dict[str, str]], OrderedDict, list[str]]:
    prompts: dict[str, dict[str, str]] = {}
    defaults: OrderedDict[str, str] = OrderedDict()
    responses: list[str] = []

    tool_material = hashlib.sha512(b"repo-behave-tools-hard-v2").digest()
    tool_parts: list[str] = []
    for index in range(40):
        first = 1 + tool_material[index] % 5
        second = 1 + tool_material[index + 23] % 5
        lower, upper = sorted((first, second))
        if index % 2 == 0 and lower != upper:
            tool_parts.append(f"{lower}-{upper}")
        else:
            tool_parts.append(str(first))
    tools_response = ", ".join(tool_parts)

    for index in range(52):
        if index == 8:
            variable_name = "tools"
            response = tools_response
            validator = r"^[0-9,\- ]+$"
        elif index == 19:
            variable_name = "example_pipeline"
            response = "YeS" if tool_material[index] % 2 else "nO"
            validator = r"(?i)^(yes|no)$"
        else:
            digest = hashlib.blake2b(
                f"prompt-{index * index * 7 + 47}".encode(), digest_size=20
            ).hexdigest()
            variable_name = f"field_{digest[:12]}"
            response = digest[5:]
            validator = r"^[a-f0-9]+$"

        prompts[variable_name] = {
            "title": f"generated title {index}",
            "text": f"Supply generated value number {index}",
            "regex_validator": validator,
            "error_message": "Generated input did not match.",
        }
        defaults[variable_name] = f"default-{index * 3}"
        responses.append(response)

    return prompts, defaults, responses


class TestGeneratedInteractiveStarter(TestCase):
    def test_cli_generated_prompt_flow(self) -> None:
        prompts, defaults, responses = _generated_prompt_data()

        def cookiecutter_dir(
            template_path: str,
            checkout: str | None,
            directory: str | None,
            tmpdir: str,
        ) -> Path:
            return Path(tmpdir)

        runner = CliRunner()
        with (
            patch(
                "kedro.framework.cli.starters._get_starters_dict",
                return_value={},
            ),
            patch(
                "kedro.framework.cli.starters._get_cookiecutter_dir",
                side_effect=cookiecutter_dir,
            ),
            patch(
                "kedro.framework.cli.starters."
                "_get_prompts_required_and_clear_from_CLI_provided",
                return_value=prompts,
            ),
            patch(
                "kedro.framework.cli.starters._make_cookiecutter_context_for_prompts",
                return_value=defaults,
            ),
            patch("kedro.framework.cli.starters._create_project") as create_project,
        ):
            result = runner.invoke(create_cli, ["new"], input="\n".join(responses) + "\n")

        self.assertEqual(result.exit_code, 0, result.output)
        create_project.assert_called_once()
        generated_context = create_project.call_args.args[1]["extra_context"]
        self.assertEqual(set(prompts), set(generated_context) - {"kedro_version"})
        self.assertTrue(all(isinstance(value, str) for value in generated_context.values()))
