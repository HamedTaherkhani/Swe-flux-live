from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from kedro.framework.cli import starters


class TestGeneratedConfigPaths(unittest.TestCase):
    def test_varied_config_files(self) -> None:
        field_names = [
            f"generated_field_{(position * position + 7 * position + 17) % 149:03d}"
            for position in range(45)
        ]
        prompts = {
            name: {"title": name.replace("_", " ").title(), "type": "string"}
            for name in field_names
        }
        prompts.update(
            {
                "tools": {"title": "Tool selection", "type": "string"},
                "example_pipeline": {"title": "Example choice", "type": "string"},
            }
        )

        outcomes: list[bool] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(41):
                mode = index % 11
                config = {
                    name: f"value-{(index + 9) * (position + 13) % 173}"
                    for position, name in enumerate(field_names)
                }

                if mode == 0:
                    payload = ""
                else:
                    if mode == 1:
                        config.pop(field_names[(index * 13 + 11) % len(field_names)])
                    elif mode == 2:
                        config["tools"] = "lint,log,pyspark"
                    elif mode == 5:
                        config["tools"] = "none"
                        config["example_pipeline"] = "NO"
                        config["output_dir"] = str(
                            root / f"missing-{index * index + 13}"
                        )
                    payload = yaml.safe_dump(config, sort_keys=False)

                config_path = root / f"scenario-{index:03d}.yml"
                config_path.write_text(payload, encoding="utf-8")
                try:
                    result = starters._get_extra_context(
                        prompts_required=prompts,
                        config_path=str(config_path),
                        cookiecutter_context=None,
                        selected_tools=None,
                        project_name=None,
                        example_pipeline=None,
                        starter_alias=None,
                    )
                except Exception:
                    outcomes.append(False)
                else:
                    self.assertIsInstance(result, dict)
                    self.assertTrue(set(field_names).issubset(result))
                    outcomes.append(True)

        self.assertEqual(len(outcomes), len(range(41)))
        self.assertTrue(any(outcomes))
        self.assertTrue(any(not outcome for outcome in outcomes))
