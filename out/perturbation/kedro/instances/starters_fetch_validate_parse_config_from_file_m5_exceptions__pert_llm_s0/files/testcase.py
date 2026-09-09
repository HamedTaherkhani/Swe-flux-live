from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml

from kedro.framework.cli.starters import _get_extra_context


def _generated_configs(root: Path) -> list[Path]:
    paths: list[Path] = []
    for index in range(91):
        digest = hashlib.blake2b(
            f"config-matrix-{index * index * 3 + index + 53}".encode(), digest_size=20
        ).hexdigest()
        path = root / f"case_{digest[:14]}.yml"
        selector = index % 7

        config: dict[str, str] = {
            "project_name": f"Project {digest[:12]}",
            "repo_name": f"repo_{digest[:10]}",
            "python_package": f"pkg_{digest[:8]}",
            "example_pipeline": (
                "yes"
                if index % 5 == 0
                else "no"
                if index % 5 == 1
                else "YES"
                if index % 5 == 2
                else "n"
                if index % 5 == 3
                else "NO"
            ),
            "tools": (
                "all"
                if index % 8 == 0
                else "none"
                if index % 8 == 1
                else "lint,test,docs"
                if index % 8 == 2
                else "pyspark,data"
                if index % 8 == 3
                else "none,lint"
                if index % 8 == 4
                else "viz"
                if index % 8 == 5
                else "log,docs,test"
                if index % 8 == 6
                else "lint,docs"
            ),
            "output_dir": (
                str(root / f"missing_{digest[:6]}")
                if index % 11 == 0
                else str(root)
            ),
        }
        if selector == 1:
            path.write_text("", encoding="utf-8")
        elif selector == 2:
            config["project_name"] = digest[:1]
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 3:
            config["example_pipeline"] = digest[:9]
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 4:
            config["tools"] = f"{digest[:5]},{digest[5:11]}"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
        elif selector == 5:
            malformed = f"{digest[:9]}{chr(9)}{digest[9:18]}{chr(10)}{digest[18:27]}"
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
                        prompts_required={
                            "project_name": {},
                            "repo_name": {},
                            "python_package": {},
                        },
                        config_path=str(path),
                        cookiecutter_context=None,
                        selected_tools=None,
                        project_name=None,
                        example_pipeline=None,
                        starter_alias="spaceflights-pandas",
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
