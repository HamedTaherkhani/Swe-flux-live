"""Deterministic exercise of the kedro new-project prompt/config pipeline.

Drives ``_get_extra_context`` (two hops above the function of interest)
repeatedly with scripted prompt answers so the tools-input parsing logic
runs once per round through several distinct control-flow shapes.
"""

import unittest
from collections import OrderedDict
from unittest import mock

from kedro.framework.cli.starters import _get_extra_context


def _prompts():
    return {
        "project_name": {"title": "Project Name"},
        "tools": {"title": "Project Tools"},
        "example_pipeline": {"title": "Example Pipeline"},
    }


def _cookiecutter_context():
    return OrderedDict(
        [
            ("project_name", "New Kedro Project"),
            ("tools", "none"),
            ("example_pipeline", "no"),
        ]
    )


def _range_token(lo, hi):
    return "-".join(str(i) for i in (lo, hi))


def _tools_strings():
    """Build the per-round tools answers programmatically."""
    rounds = []
    # Round 1: the 'select everything' keyword, spelled with mixed case.
    rounds.append("".join(["A", "l"]) + "L")
    # Round 2: the 'select nothing' keyword, assembled from pieces.
    rounds.append("No" + "n" + "e")
    # Round 3: two single picks instead of one contiguous range.
    rounds.append(", ".join([str(1), str(2)]))
    # Round 4: a long mixed list with spaces, single picks and ranges
    # (including degenerate one-element ranges and repeated selections).
    tokens = [
        str(2),
        _range_token(4, 5),
        str(1),
        str(3),
        "-".join([str(6), str(6)]),
        _range_token(1, 2),
        str(3),
        str(4),
        str(5),
        _range_token(3, 5),
        _range_token(4, 4),
        str(5),
    ]
    rounds.append(", ".join(tokens))
    # Round 5: a degenerate one-element range for a single pick.
    rounds.append(_range_token(5, 5))
    # Round 6: three single picks instead of a range plus one pick.
    rounds.append(", ".join([str(3), str(4), str(6)]))
    # Round 7: full-span range from first through last tool.
    rounds.append(_range_token(1, 6))
    # Round 8: every tool selected as an individual comma-separated pick.
    rounds.append(", ".join(str(i) for i in (1, 2, 3, 4, 5, 6)))
    return rounds


class TestParseToolsInputCfgRuntime(unittest.TestCase):
    def test_traced_run(self):
        tools_rounds = _tools_strings()
        project_names = ["Proj %s" % suffix for suffix in "ABCDEFGH"]
        example_flags = ["yes", "no", "no", "yes", "no", "yes", "no", "yes"]

        # click.prompt is called once per prompt per round, in prompts order.
        answers = []
        for name, tools, flag in zip(project_names, tools_rounds, example_flags):
            answers.extend([name, tools, flag])

        results = []
        with mock.patch("click.prompt", side_effect=answers) as mock_prompt:
            for _ in range(len(tools_rounds)):
                results.append(
                    _get_extra_context(
                        _prompts(),
                        None,
                        _cookiecutter_context(),
                        None,
                        None,
                        None,
                        None,
                    )
                )

        self.assertEqual(mock_prompt.call_count, 3 * len(tools_rounds))
        self.assertEqual(len(results), len(tools_rounds))

        # Round-level sanity assertions on the produced extra_context.
        all_tools = results[0]["tools"]
        for readable in (
            "Linting",
            "Testing",
            "Custom Logging",
            "Documentation",
            "Data Structure",
            "PySpark",
        ):
            self.assertIn(readable, all_tools)

        self.assertEqual(results[1]["tools"], str(["None"]))

        self.assertIn("Linting", results[2]["tools"])
        self.assertIn("Testing", results[2]["tools"])
        self.assertNotIn("PySpark", results[2]["tools"])

        mixed = results[3]["tools"]
        self.assertEqual(mixed.count("Linting"), 2)
        self.assertEqual(mixed.count("Testing"), 2)
        self.assertEqual(mixed.count("PySpark"), 1)
        self.assertIn("Data Structure", mixed)

        self.assertEqual(results[4]["tools"], str(["Data Structure"]))

        self.assertIn("Custom Logging", results[5]["tools"])
        self.assertIn("Documentation", results[5]["tools"])
        self.assertIn("PySpark", results[5]["tools"])
        self.assertNotIn("Linting", results[5]["tools"])

        for result, flag in zip(results, example_flags):
            expected = "True" if flag == "yes" else "False"
            self.assertEqual(result["example_pipeline"], expected)
            self.assertIn("kedro_version", result)


if __name__ == "__main__":
    unittest.main()
