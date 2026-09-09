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
    short = {"lint": "lint", "test": "test", "data": "data", "pyspark": "pyspark"}
    comma = ", "
    rounds = [
        # no starter: tools/example flags steer the tool/example branches
        dict(starter_alias=None, selected_tools=short["pyspark"],
             example_pipeline=None, checkout=None, directory=None),
        dict(starter_alias=None, selected_tools=comma.join([short["lint"], short["test"]]),
             example_pipeline="yes", checkout=None, directory=None),
        dict(starter_alias=None, selected_tools="none",
             example_pipeline="no", checkout=None, directory=None),
        # non-alias starter path: checkout and directory pass straight through
        dict(starter_alias="custom-" + "starter", selected_tools=None,
             example_pipeline=None, checkout="v" + "0.0.1-test",
             directory=("/").join(["some", "nested", "dir"])),
        # official starter alias: directory comes from the starter spec
        dict(starter_alias="astro-airflow-iris", selected_tools=None,
             example_pipeline=None, checkout=None, directory=None),
        dict(starter_alias=None, selected_tools="all",
             example_pipeline="yes", checkout=None, directory=None),
        dict(starter_alias=None,
             selected_tools=comma.join([short["pyspark"], short["lint"]]),
             example_pipeline="no", checkout=None, directory=None),
        dict(starter_alias=None, selected_tools=short["data"],
             example_pipeline="yes", checkout=None, directory=None),
    ]
    return rounds


class TestCookiecutterArgsDataFlow(unittest.TestCase):
    def test_traced_run(self):
        rounds = _round_specs()

        fake_cookiecutter_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fake_cookiecutter_dir, True)
        (fake_cookiecutter_dir / "cookiecutter.json").write_text(
            json.dumps({"project_name": "Placeholder Project"})
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
                    project_name=None,
                    checkout=spec["checkout"],
                    directory=spec["directory"],
                    example_pipeline=spec["example_pipeline"],
                    telemetry_consent=None,
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
        pyspark_rounds = {0, 5, 6}
        example_rounds = {1, 7}
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
