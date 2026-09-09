"""Deterministic exercise of the kedro `new` command pipeline.

Drives the public ``new`` command callback (one hop above the function of
interest) through eight scripted rounds with varying --starter / --tools /
--example / --checkout / --directory flag combinations, so that the
cookiecutter-argument assembly logic runs once per round through several
distinct control-flow shapes.  Template fetching and project creation are
mocked out; everything else runs for real.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kedro.framework.cli.starters import new


def _round_specs():
    """Build the per-round flag combinations programmatically."""
    short = {"lint": "lint", "test": "test", "data": "data", "pyspark": "pyspark",
             "log": "log", "docs": "docs", "tests": "tests", "logs": "logs", "doc": "doc"}
    comma = ", "
    rounds = [
        # no starter: tools/example flags steer the tool/example branches
        dict(starter_alias=None, selected_tools=short["pyspark"],
             example_pipeline=None, checkout=None, directory=None,
             project_name="spark-benchmark-project", telemetry_consent="yes"),
        dict(starter_alias=None, selected_tools=comma.join([short["lint"], short["test"]]),
             example_pipeline="YES", checkout=None, directory=None,
             project_name="pandas-pipeline-alpha", telemetry_consent="no"),
        dict(starter_alias=None, selected_tools="none",
             example_pipeline="NO", checkout=None, directory=None,
             project_name=None, telemetry_consent="y"),
        # non-alias starter path: checkout and directory pass straight through
        dict(starter_alias="custom-" + "starter-v2", selected_tools=None,
             example_pipeline=None, checkout="release/" + "2.1.0-rc1",
             directory=("/").join(["deeply", "nested", "custom", "starter", "dir"]),
             project_name="custom-starter-project", telemetry_consent="n"),
        # official starter alias: directory comes from the starter spec
        dict(starter_alias="databricks-iris", selected_tools=None,
             example_pipeline=None, checkout="main", directory=None,
             project_name="databricks-iris-bench", telemetry_consent=None),
        dict(starter_alias=None, selected_tools="all",
             example_pipeline="y", checkout=None, directory=None,
             project_name="all-tools-project", telemetry_consent="yes"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["pyspark"], short["lint"], short["log"]]),
             example_pipeline="n", checkout=None, directory=None,
             project_name="pyspark-lint-log", telemetry_consent="no"),
        dict(starter_alias=None, selected_tools=short["data"],
             example_pipeline="Yes", checkout=None, directory=None,
             project_name="data-example-beta", telemetry_consent="y"),
        dict(starter_alias=None, selected_tools=short["pyspark"],
             example_pipeline="no", checkout=None, directory=None,
             project_name="pyspark-only-gamma", telemetry_consent="n"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["doc"], short["docs"], short["data"]]),
             example_pipeline="yes", checkout=None, directory=None,
             project_name="docs-data-example", telemetry_consent=None),
        dict(starter_alias=None, selected_tools="NONE",
             example_pipeline="N", checkout=None, directory=None,
             project_name=None, telemetry_consent="yes"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["tests"], short["logs"], short["pyspark"]]),
             example_pipeline="No", checkout=None, directory=None,
             project_name="alias-tools-delta", telemetry_consent="no"),
        dict(starter_alias=None, selected_tools=short["test"],
             example_pipeline="Y", checkout=None, directory=None,
             project_name="single-test-yes", telemetry_consent="y"),
        dict(starter_alias=None, selected_tools=comma.join([short["lint"], short["doc"]]),
             example_pipeline="no", checkout=None, directory=None,
             project_name="lint-doc-none", telemetry_consent="n"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["pyspark"], short["data"]]),
             example_pipeline="YES", checkout=None, directory=None,
             project_name="pyspark-data-yes", telemetry_consent=None),
        dict(starter_alias=None, selected_tools=comma.join([short["lint"], short["docs"]]),
             example_pipeline=None, checkout=None, directory=None,
             project_name="lint-docs-default", telemetry_consent="yes"),
        dict(starter_alias=None, selected_tools=short["pyspark"],
             example_pipeline=None, checkout=None, directory=None,
             project_name="pyspark-repeat-epsilon", telemetry_consent="no"),
        dict(starter_alias=None, selected_tools=short["log"],
             example_pipeline="yes", checkout=None, directory=None,
             project_name="log-only-example", telemetry_consent="y"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["data"], short["lint"]]),
             example_pipeline="NO", checkout=None, directory=None,
             project_name=None, telemetry_consent="n"),
        dict(starter_alias=None,
             selected_tools=comma.join([short["pyspark"], short["test"]]),
             example_pipeline="yes", checkout=None, directory=None,
             project_name="pyspark-test-yes", telemetry_consent=None),
    ]
    return rounds


class TestCookiecutterArgsDataFlow(unittest.TestCase):
    def test_traced_run(self):
        rounds = _round_specs()

        fake_cookiecutter_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fake_cookiecutter_dir, True)
        (fake_cookiecutter_dir / "cookiecutter.json").write_text(
            json.dumps({"project_name": "Benchmark Kedro Project"})
        )

        with mock.patch(
            "kedro.framework.cli.starters._get_cookiecutter_dir",
            return_value=fake_cookiecutter_dir,
        ), mock.patch(
            "kedro.framework.cli.starters._create_project"
        ) as mock_create:
            for spec in rounds:
                new.callback(
                    config_path=None,
                    starter_alias=spec["starter_alias"],
                    selected_tools=spec["selected_tools"],
                    project_name=spec["project_name"],
                    checkout=spec["checkout"],
                    directory=spec["directory"],
                    example_pipeline=spec["example_pipeline"],
                    telemetry_consent=spec["telemetry_consent"],
                )

        self.assertEqual(mock_create.call_count, len(rounds))

        seen = [call.args for call in mock_create.call_args_list]

        # Every round must hand cookiecutter a well-formed argument bundle.
        for _template, cargs, _consent in seen:
            self.assertTrue(cargs["no_input"])
            self.assertIn("checkout", cargs)
            self.assertIn("output_dir", cargs)
            self.assertIn("kedro_version", cargs["extra_context"])

        # Rounds whose tools selection contains the PySpark short name must
        # land on the PySpark starter directory; rounds with an affirmative
        # example flag but no PySpark land on the pandas starter directory.
        pyspark_rounds = {0, 5, 6, 8, 11, 14, 16, 19}
        example_rounds = {1, 7, 9, 12, 17}
        for idx, (template, cargs, _consent) in enumerate(seen):
            if idx in pyspark_rounds:
                self.assertEqual(cargs["directory"].count("pyspark"), 1)
                self.assertIn("kedro-starters", template)
            elif idx in example_rounds:
                self.assertEqual(cargs["directory"].count("pandas"), 1)
            elif idx == 3:
                self.assertTrue(cargs["directory"].endswith("dir"))
                self.assertEqual(template, rounds[idx]["starter_alias"])
            elif idx == 4:
                self.assertEqual(cargs["directory"], rounds[idx]["starter_alias"])
            else:
                self.assertNotIn("directory", cargs)


if __name__ == "__main__":
    unittest.main()
