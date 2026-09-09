from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from kedro.templates.project.hooks import utils


class TestPySparkStarterCleanup(unittest.TestCase):
    def test_generated_project_cleanup(self) -> None:
        generator = random.Random(58391)
        original_current_dir = utils.current_dir

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                suite_root = Path(temporary_directory)

                for project_index in range(22):
                    project_root = suite_root / f"project_{project_index}"
                    package_name = f"package_{project_index}"
                    raw_data = project_root / "data" / "01_raw"
                    conf_base = project_root / "conf" / "base"
                    pipelines = project_root / "src" / package_name / "pipelines"

                    raw_data.mkdir(parents=True)
                    conf_base.mkdir(parents=True)
                    pipelines.mkdir(parents=True)

                    raw_file_count = generator.randint(6, 112)
                    suffixes = (".csv", ".json", ".xlsx", ".csv", ".xlsx", ".json", ".csv")
                    for file_index in range(raw_file_count):
                        suffix = suffixes[
                            (file_index * 17 + project_index * 7) % len(suffixes)
                        ]
                        (raw_data / f"asset_{project_index}_{file_index}{suffix}").write_text(
                            f"{generator.randrange(9_999_999)}\n"
                        )

                    (conf_base / "catalog.yml").write_text("source: generated\n")
                    for parameter_index in range(
                        generator.randrange(6, 24) + (project_index * 3) % 13
                    ):
                        if parameter_index % 3:
                            parameter_path = (
                                conf_base
                                / "parameters"
                                / f"group_{project_index}_{parameter_index}.yml"
                            )
                        else:
                            parameter_path = (
                                conf_base
                                / f"parameters_{project_index}_{parameter_index}.yml"
                            )
                        parameter_path.parent.mkdir(parents=True, exist_ok=True)
                        parameter_path.write_text(
                            f"value: {generator.randrange(9_999_999)}\n"
                        )

                    for pipeline_name in (
                        "data_science",
                        "data_processing",
                        "reporting",
                    ):
                        pipeline_directory = pipelines / pipeline_name
                        pipeline_directory.mkdir()
                        (pipeline_directory / "nodes.py").write_text(
                            f"MARKER = {generator.randrange(9_999_999)}\n"
                        )

                    test_pipeline = (
                        project_root
                        / "tests"
                        / "pipelines"
                        / "data_science"
                        / "test_pipeline.py"
                    )
                    test_pipeline.parent.mkdir(parents=True)
                    test_pipeline.write_text("def test_placeholder():\n    pass\n")

                    requirements = project_root / "requirements.txt"
                    requirements.write_text(
                        "kedro-datasets[pandas.CSVDataset,spark.SparkDataset]~=1.2\n"
                        "seaborn~=0.12.1\n"
                        "scikit-learn~=1.0\n"
                        "requests>=2\n"
                        "pyspark~=3.4\n"
                    )
                    pyproject = project_root / "pyproject.toml"
                    pyproject.write_text("[project]\nname = 'generated-project'\n")

                    utils.current_dir = project_root
                    utils.setup_template_tools(
                        "Linting Testing Logging Documentation Data Structure PySpark",
                        requirements,
                        pyproject,
                        package_name,
                        "False",
                    )

                    self.assertEqual((conf_base / "catalog.yml").read_text(), "")
                    self.assertTrue(all(path.suffix == ".json" for path in raw_data.iterdir()))
                    self.assertFalse(any(pipelines.iterdir()))
                    self.assertFalse(test_pipeline.parent.exists())
                    self.assertIn("requests>=2", requirements.read_text())
        finally:
            utils.current_dir = original_current_dir
