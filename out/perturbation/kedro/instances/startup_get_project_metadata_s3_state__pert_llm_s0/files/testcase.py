from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock

import toml

from kedro import __version__ as kedro_version
from kedro.framework import startup


class TestBootstrapMetadataState(unittest.TestCase):
    def test_generated_project_matrix(self) -> None:
        workspace = Path.cwd() / "data" / "repo_behave_startup_state_extended_matrix"
        shutil.rmtree(workspace, ignore_errors=True)
        workspace.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, workspace, True)

        project_count = sum(
            (ord(character) % 5) + 1
            for character in "metadata_state_trace_local_observation_matrix_seed"
        )
        rolling_token = sum(
            (position + 3) * ord(character)
            for position, character in enumerate("bootstrap_project_matrix_seed_v2")
        )
        project_paths = []

        for index in range(project_count):
            rolling_token = (rolling_token * 73 + index * index + 41) % 1_000_003
            project_path = workspace / f"project_{index:02d}_{rolling_token:06d}"
            project_path.mkdir()

            metadata = {
                "package_name": (
                    f"pkg_{(rolling_token ^ (index * 257)):x}_{index:02d}"
                ),
                "project_name": "".join(
                    chr(65 + ((rolling_token // (position + 1) + index) % 26))
                    for position in range(12)
                ),
                "kedro_init_version": (
                    f"{'.'.join(kedro_version.split('.')[:2])}.{index % 10}"
                ),
            }
            if index % 2 == 0:
                metadata["source_dir"] = (
                    f"~/generated/nested/{(rolling_token + index * 19) % 1009:03d}/src"
                )
            if index % 3 != 0:
                metadata["tools"] = [
                    f"tool_{(rolling_token + offset * (index + 7)) % 97:02d}"
                    for offset in range(index % 7 + 3)
                ]
            if index % 4 != 1:
                metadata["example_pipeline"] = (
                    f"pipe_{(rolling_token * (index + 11)) % 100_003:05d}"
                )

            config = {"tool": {"kedro": metadata}}
            (project_path / "pyproject.toml").write_text(
                toml.dumps(config), encoding="utf-8"
            )
            project_paths.append(project_path)

        with (
            mock.patch.object(startup, "_add_src_to_path") as add_src,
            mock.patch.object(startup, "configure_project") as configure,
        ):
            results = [
                startup.bootstrap_project(str(path))
                for path in project_paths
            ]

        self.assertEqual(len(results), project_count)
        self.assertEqual(add_src.call_count, project_count)
        self.assertEqual(configure.call_count, project_count)
        self.assertTrue(all(result.project_path.is_absolute() for result in results))
        self.assertTrue(all(result.config_file.is_file() for result in results))