from __future__ import annotations

import random
import unittest
from pathlib import Path
from unittest.mock import patch

import kedro.framework.cli.starters as starters


class TestNewProgramState(unittest.TestCase):
    def test_seeded_direct_invocations(self) -> None:
        seed = sum((index + 1) * ord(char) for index, char in enumerate(__name__))
        rng = random.Random(seed)
        alphabet = "abcdefghjkmnpqrstuvwxyz"

        aliases = [
            "".join(rng.choice(alphabet) for _ in range(7))
            for _ in range(4)
        ]
        specs = {
            alias: starters.KedroStarterSpec(
                alias,
                "/catalog/" + "".join(reversed(alias)),
                "segment-" + str(sum(map(ord, alias)) % 17),
            )
            for alias in aliases
        }

        cases = []
        tool_names = ("lint", "test", "log", "docs", "data")
        for index in range(24):
            branch = index % 5
            if branch in (0, 1, 3):
                starter_alias = None
                width = 1 + rng.randrange(4)
                selected_tools = ",".join(
                    tool_names[(rng.randrange(len(tool_names)) + index) % len(tool_names)]
                    for _ in range(width)
                )
                example_pipeline = ("y", "n")[(rng.randrange(9) + index) % 2]
            elif branch == 2:
                starter_alias = "/custom/" + "".join(
                    rng.choice(alphabet) for _ in range(9)
                )
                selected_tools = None
                example_pipeline = None
            else:
                starter_alias = aliases[(index + rng.randrange(len(aliases))) % len(aliases)]
                selected_tools = None
                example_pipeline = None

            project_name = "Project " + "".join(
                rng.choice(alphabet) for _ in range(6 + index % 4)
            )
            config_path = (
                "/config/" + str((index * index + rng.randrange(97)) % 101) + ".yml"
                if index % 6 == 3
                else None
            )
            revision_number = (rng.randrange(200) * (index + 3)) % 137
            checkout = (
                "rev-" + str(revision_number)
                if starter_alias is not None and index % 4
                else None
            )
            telemetry = ("yes", "no", "y", "n", None)[
                (rng.randrange(31) + index) % 5
            ]
            cases.append(
                {
                    "config_path": config_path,
                    "starter_alias": starter_alias,
                    "selected_tools": selected_tools,
                    "project_name": project_name,
                    "checkout": checkout,
                    "directory": None,
                    "example_pipeline": example_pipeline,
                    "telemetry_consent": telemetry,
                }
            )

        helper_calls = {"prompts": 0, "context": 0, "extra": 0, "args": 0}
        creations = []
        selections = []

        def fake_cookiecutter_dir(template_path, checkout, directory, tmpdir):
            del tmpdir
            score = sum(map(ord, str(template_path)))
            score += sum(map(ord, str(checkout)))
            score += 7 * len(str(directory))
            return Path("/virtual") / f"template-{score % 211}"

        def fake_prompts(cookiecutter_dir, selected_tools, project_name, example_pipeline):
            helper_calls["prompts"] += 1
            score = (
                sum(map(ord, str(cookiecutter_dir)))
                + sum(map(ord, str(selected_tools)))
                + sum(map(ord, str(project_name)))
                + sum(map(ord, str(example_pipeline)))
                + helper_calls["prompts"] * 13
            )
            keys = ("owner", "purpose", "region", "schedule", "quality")
            return {
                keys[position]: (score + position * position) % 29
                for position in range(score % 4)
            }

        def fake_context(cookiecutter_dir):
            helper_calls["context"] += 1
            base = sum(map(ord, cookiecutter_dir.as_posix()))
            return {
                "context_code": (base * helper_calls["context"]) % 307,
                "context_depth": len(cookiecutter_dir.parts),
            }

        def fake_extra_context(
            prompts_required,
            config_path,
            cookiecutter_context,
            selected_tools,
            project_name,
            example_pipeline,
            starter_alias,
        ):
            helper_calls["extra"] += 1
            material = "|".join(
                map(
                    str,
                    (
                        sorted(prompts_required.items()),
                        config_path,
                        cookiecutter_context,
                        selected_tools,
                        project_name,
                        example_pipeline,
                        starter_alias,
                        helper_calls["extra"],
                    ),
                )
            )
            rolling = 0
            for position, char in enumerate(material):
                rolling = (rolling + (position + 5) * ord(char)) % 10007
            return {
                "signature": rolling,
                "tools": str(selected_tools).swapcase(),
                "example_pipeline": str(
                    bool(example_pipeline)
                    and sum(map(ord, str(example_pipeline))) % 2 == 0
                ),
                "name_code": sum(map(ord, str(project_name))) % 313,
                "prompt_keys": tuple(sorted(prompts_required)),
            }

        def fake_args(config, checkout, directory, template_path):
            helper_calls["args"] += 1
            ordered = tuple((key, config[key]) for key in sorted(config))
            weighted = sum(
                (position + 1) * ord(char)
                for position, char in enumerate(repr(ordered))
            )
            args = {
                "payload": ordered,
                "revision_code": sum(map(ord, str(checkout))) % 257,
                "directory_size": len(str(directory)),
                "sequence": helper_calls["args"],
            }
            project_template = (
                f"/generated/{(weighted + sum(map(ord, str(template_path)))) % 409}"
            )
            return args, project_template

        def fake_create(project_template, cookiecutter_args, telemetry_consent):
            creations.append(
                (
                    len(project_template),
                    len(cookiecutter_args["payload"]),
                    telemetry_consent,
                )
            )

        def fake_selection(selected_tools, example_pipeline, interactive):
            selections.append(
                (len(selected_tools), len(example_pipeline), bool(interactive))
            )

        patches = (
            patch.object(starters, "_get_starters_dict", return_value=specs),
            patch.object(starters, "_get_cookiecutter_dir", side_effect=fake_cookiecutter_dir),
            patch.object(
                starters,
                "_get_prompts_required_and_clear_from_CLI_provided",
                side_effect=fake_prompts,
            ),
            patch.object(
                starters,
                "_make_cookiecutter_context_for_prompts",
                side_effect=fake_context,
            ),
            patch.object(starters.shutil, "rmtree", return_value=None),
            patch.object(starters.tempfile, "mkdtemp", side_effect=lambda: "/discarded"),
            patch.object(starters, "_get_extra_context", side_effect=fake_extra_context),
            patch.object(
                starters,
                "_make_cookiecutter_args_and_fetch_template",
                side_effect=fake_args,
            ),
            patch.object(starters, "_create_project", side_effect=fake_create),
            patch.object(
                starters,
                "_print_selection_and_prompt_info",
                side_effect=fake_selection,
            ),
        )

        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

        for case in cases:
            starters.new.callback(**case)

        self.assertEqual(len(creations), len(cases))
        self.assertEqual(
            len(selections),
            sum(case["starter_alias"] is None for case in cases),
        )
        self.assertTrue(all(len(record) == 3 for record in creations))
        self.assertGreater(len({record[:2] for record in creations}), 1)
