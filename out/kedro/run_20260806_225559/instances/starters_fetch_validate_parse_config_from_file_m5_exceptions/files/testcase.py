from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml

from kedro.framework.cli.starters import _get_extra_context


def _generated_configs(root: Path) -> list[Path]:
    paths: list[Path] = []
    for index in range(21):
        digest = hashlib.blake2b(
            f"config-case-{index * index + 29}".encode(), digest_size=18
        ).hexdigest()
        path = root / f"case_{digest[:12]}.yml"
        selector = index % 7

        config: dict[str, str] = {
            "project_name": f"Project {digest[:10]}",
            "example_pipeline": "yes" if index % 2 else "no",
            "tools": "lint,docs" if index % 3 else "all",
            "output_dir": str(root),
        }
        if selector == 1:
            path.write_text("", encoding="utf-8")
        elif selector == 2:
            config["project_name"] = digest[:1]
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 3:
            config["example_pipeline"] = digest[:8]
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 4:
            config["tools"] = f"{digest[:6]},{digest[6:12]}"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 5:
            malformed = f"{digest[:7]}{chr(9)}{digest[7:14]}"
            path.write_text(malformed, encoding="utf-8")
        elif selector == 6:
            config.pop("tools")
            config.pop("example_pipeline")
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        paths.append(path)
    return paths


class TestGeneratedConfigExceptionLayers(TestCase):
    def test_indirect_generated_config_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _generated_configs(Path(directory))
            completed: list[bool] = []
            returned: list[dict[str, str]] = []

            for path in paths:
                try:
                    result = _get_extra_context(
                        prompts_required={"project_name": {}},
                        config_path=str(path),
                        cookiecutter_context=None,
                        selected_tools=None,
                        project_name=None,
                        example_pipeline=None,
                        starter_alias=None,
                    )
                except BaseException:
                    completed.append(False)
                else:
                    completed.append(True)
                    returned.append(result)

            self.assertEqual(len(completed), len(paths))
            self.assertTrue(any(completed))
            self.assertTrue(any(not outcome for outcome in completed))
            self.assertTrue(returned)
            self.assertTrue(
                all(
                    isinstance(value, str)
                    for config in returned
                    for value in config.values()
                )
            )
