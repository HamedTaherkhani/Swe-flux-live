import random
import tempfile
import unittest
from pathlib import Path

import toml

from kedro.templates.project.hooks import utils as template_utils
from kedro.templates.project.hooks.utils import setup_template_tools


class TestSetupTemplateToolsCalls(unittest.TestCase):
    def test_programmatic_template_cleanup_call_order(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            requirements_path = project_root / "requirements.txt"
            pyproject_path = project_root / "pyproject.toml"

            pyproject_data = {
                "project": {
                    "name": "generated-project",
                    "optional-dependencies": {
                        "dev": ["pytest", "ruff"],
                        "docs": ["sphinx"],
                    },
                },
                "tool": {
                    "ruff": {
                        "format": {"quote-style": "double"},
                        "lint": {"select": ["E", "F"]},
                    },
                    "pytest": {"ini_options": {"addopts": "-q"}},
                    "coverage": {"report": {"show_missing": True}},
                },
            }
            pyproject_path.write_text(toml.dumps(pyproject_data), encoding="utf-8")

            generated_requirements = [
                f"kedro-datasets[feature_{index}]>={index % 4}.{index % 7}\n"
                for index in range(23)
            ]
            generated_requirements.extend(
                [
                    template_utils.example_pipeline_requirements,
                    "click>=8\n",
                    "toml>=0.10\n",
                ]
            )
            requirements_path.write_text(
                "".join(generated_requirements), encoding="utf-8"
            )

            paths_to_create = [
                project_root / "conf/logging.yml",
                project_root / "conf/base/catalog.yml",
                project_root
                / "tests/pipelines/data_science/test_pipeline.py",
                project_root / "docs/index.rst",
            ]
            paths_to_create.extend(
                project_root / f"conf/base/parameters_group_{index:02d}.yml"
                for index in range(19)
            )
            paths_to_create.extend(
                project_root / f"conf/base/parameters/segment_{index:02d}.yml"
                for index in range(17)
            )
            paths_to_create.extend(
                project_root / f"data/01_raw/batch_{index:02d}.{('csv', 'xlsx', 'txt')[index % 3]}"
                for index in range(27)
            )
            paths_to_create.extend(
                project_root / f"src/generated_pkg/pipelines/{pipeline}/nodes.py"
                for pipeline in ("data_science", "data_processing", "reporting")
            )

            randomizer = random.Random(8675309)
            randomizer.shuffle(paths_to_create)
            for index, file_path in enumerate(paths_to_create):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(f"generated-{index}\n", encoding="utf-8")

            all_tool_names = (
                "Linting",
                "Testing",
                "Logging",
                "Documentation",
                "Data Structure",
                "PySpark",
            )
            selected_tools = ",".join(
                name
                for name in all_tool_names
                if name.startswith("P") or any(character.isspace() for character in name)
            )

            original_current_dir = template_utils.current_dir
            template_utils.current_dir = project_root
            try:
                setup_template_tools(
                    selected_tools,
                    requirements_path,
                    pyproject_path,
                    "generated_pkg",
                    str(bool(len(selected_tools) % 2)),
                )
            finally:
                template_utils.current_dir = original_current_dir

            remaining_requirements = requirements_path.read_text(encoding="utf-8")
            self.assertNotIn("[", remaining_requirements)
            self.assertTrue((project_root / "data/01_raw").is_dir())
            self.assertFalse((project_root / "tests").exists())
            self.assertEqual(
                (project_root / "conf/base/catalog.yml").read_text(encoding="utf-8"),
                "",
            )


if __name__ == "__main__":
    unittest.main()
