from __future__ import annotations

import importlib
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner


class TestPipelineSyncDataFlow(unittest.TestCase):
    def test_generated_create_tree(self) -> None:
        pipeline_cli = importlib.import_module("kedro.framework.cli.pipeline")
        rng = random.Random(7301)

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = Path(temporary_directory) / "project"
            rendered_path = project_path / "rendered"
            template_path = project_path / "template"
            source_dir = project_path / "src"
            pipeline_name = "generated_flow"

            template_path.mkdir(parents=True)
            (project_path / "conf" / "base").mkdir(parents=True)

            metadata = SimpleNamespace(
                source_dir=source_dir,
                package_name="generated_package",
                project_path=project_path,
                project_name="project_workspace",
            )

            tokens = [f"{rng.randrange(1_000_000):06d}" for _ in range(41)]

            def populate(source_root: Path, target_root: Path, salt: int) -> None:
                source_root.mkdir(parents=True)
                target_root.mkdir(parents=True, exist_ok=True)

                for index, token in enumerate(tokens[:27]):
                    name = f"item_{salt}_{index:02d}_{token}.txt"
                    source_file = source_root / name
                    source_file.write_text(
                        f"{token[::-1]}:{index * index + salt}\n", encoding="utf-8"
                    )
                    target_entry = target_root / name
                    if index % 6 == 0:
                        target_entry.mkdir()
                    elif index % 4 == 0:
                        target_entry.write_text("preserved\n", encoding="utf-8")

                for group_index, token in enumerate(tokens[27:35]):
                    group_name = f"group_{salt}_{group_index:02d}_{token}"
                    source_group = source_root / group_name
                    source_group.mkdir()
                    target_group = target_root / group_name
                    if group_index % 2 == 0:
                        target_group.mkdir()

                    for child_index in range(4):
                        child_name = (
                            f"child_{child_index}_{tokens[group_index + child_index]}.dat"
                        )
                        (source_group / child_name).write_text(
                            f"{salt + group_index}:{child_index}\n", encoding="utf-8"
                        )
                        if group_index % 2 == 0 and child_index == group_index % 4:
                            (target_group / child_name).write_text(
                                "older\n", encoding="utf-8"
                            )

            tests_target = (
                project_path / "tests" / "pipelines" / pipeline_name
            )
            config_target = project_path / "conf" / "base"
            populate(rendered_path / "tests", tests_target, 3)
            populate(rendered_path / "config", config_target, 11)

            with patch(
                "kedro.framework.cli.pipeline._create_pipeline",
                return_value=rendered_path,
            ):
                result = CliRunner().invoke(
                    pipeline_cli.pipeline,
                    [
                        "create",
                        pipeline_name,
                        "--template",
                        str(template_path),
                        "--env",
                        "base",
                    ],
                    obj=metadata,
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse((rendered_path / "tests").exists())
            self.assertFalse((rendered_path / "config").exists())
            self.assertGreater(
                sum(path.is_file() for path in project_path.rglob("*")), len(tokens)
            )
