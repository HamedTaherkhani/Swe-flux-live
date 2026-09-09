import json
import tempfile
import unittest
from pathlib import Path

from repogen.rollout_effort import (
    _four_level_cutoffs,
    _four_level_label,
    build_report,
    extract_trajectory,
)


class RolloutEffortTests(unittest.TestCase):
    def test_observed_effort_uses_four_quartile_levels(self):
        cutoffs = _four_level_cutoffs([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(cutoffs, (1.75, 2.5, 3.25))
        self.assertEqual(_four_level_label(1.0, *cutoffs), "easy")
        self.assertEqual(_four_level_label(2.0, *cutoffs), "medium")
        self.assertEqual(_four_level_label(3.0, *cutoffs), "hard")
        self.assertEqual(_four_level_label(4.0, *cutoffs), "very_hard")

    def _make_run(self, root: Path) -> tuple[Path, Path]:
        run_dir = root / "repo" / "run_1"
        trajectory_dir = (
            run_dir / "validation" / "solver_agent" / "claude-code" / "model-a"
            / "instance-a" / "rollout_1"
        )
        trajectory_dir.mkdir(parents=True)
        trajectory = trajectory_dir / "instance-a.traj.json"
        events = [
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "Inspect and execute."},
                        {
                            "type": "tool_use",
                            "id": "read-1",
                            "name": "Read",
                            "input": {"file_path": "/testbed/pkg/source.py"},
                        },
                    ]
                },
            },
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "read-1",
                            "content": "line one\nline two",
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:02Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "bash-1",
                            "name": "Bash",
                            "input": {
                                "command": (
                                    "pytest tests/test_source.py && echo '{}' > "
                                    "/testbed/validation_answers/instance-a/rollout_1/answer.json"
                                )
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "write-1",
                            "name": "Write",
                            "input": {
                                "file_path": "/testbed/validation_answers/instance-a/rollout_1/answer.json",
                                "content": "{}",
                            },
                        },
                    ]
                },
            },
            {
                "type": "result",
                "timestamp": "2026-01-01T00:00:05Z",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 5000,
                "num_turns": 2,
                "modelUsage": {
                    "model-a": {
                        "inputTokens": 100,
                        "outputTokens": 50,
                        "cacheCreationInputTokens": 200,
                        "cacheReadInputTokens": 300,
                        "costUSD": 0.01,
                    }
                },
            },
        ]
        trajectory.write_text(json.dumps({"events": events}), encoding="utf-8")
        return run_dir, trajectory

    def test_extracts_tool_exploration_execution_and_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, trajectory = self._make_run(Path(temp_dir))
            record = extract_trajectory(run_dir, trajectory)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["activity"]["tool_calls"], 3)
            self.assertEqual(record["activity"]["tool_types"], {"Bash": 1, "Read": 1, "Write": 1})
            self.assertEqual(record["exploration"]["unique_source_files_read"], 1)
            self.assertEqual(record["execution"]["test_commands"], 1)
            self.assertEqual(record["execution"]["answer_writes"], 2)
            self.assertEqual(record["execution"]["answer_revisions"], 1)
            self.assertEqual(record["resources"]["context_tokens"], 600)
            self.assertEqual(record["resources"]["total_tokens"], 650)
            self.assertEqual(record["timing"]["seconds_to_first_execution"], 2.0)
            self.assertEqual(record["timing"]["seconds_to_first_answer_write"], 2.0)

    def test_oracle_outcome_is_joined_after_effort_scoring(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, _ = self._make_run(Path(temp_dir))

            def write_validation(passed: bool) -> None:
                validation = {
                    "runs": [{
                        "scope": "claude-code/model-a",
                        "verdicts": [{
                            "instance_id": "instance-a",
                            "details": {
                                "rollouts": [{
                                    "rollout": 1,
                                    "passed": passed,
                                    "reason": "matched" if passed else "mismatch",
                                }]
                            },
                        }],
                    }]
                }
                (run_dir / "validation_report.json").write_text(
                    json.dumps(validation), encoding="utf-8"
                )

            write_validation(False)
            failed = build_report([run_dir])
            write_validation(True)
            passed = build_report([run_dir])
            failed_record = failed["rollouts"][0]
            passed_record = passed["rollouts"][0]
            self.assertEqual(failed_record["raw_effort"], passed_record["raw_effort"])
            self.assertEqual(
                failed_record["observed_effort_score"], passed_record["observed_effort_score"]
            )
            self.assertFalse(failed_record["matched_oracle"])
            self.assertTrue(passed_record["matched_oracle"])

    def test_matched_rollouts_are_averaged_per_instance_before_downstream_accuracy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, first_path = self._make_run(Path(temp_dir))
            first_document = json.loads(first_path.read_text(encoding="utf-8"))
            for rollout in (2, 3):
                rollout_dir = first_path.parents[1] / f"rollout_{rollout}"
                rollout_dir.mkdir()
                document = json.loads(json.dumps(first_document))
                if rollout == 2:
                    document["events"][0]["message"]["content"].append({
                        "type": "tool_use",
                        "id": "extra-read",
                        "name": "Read",
                        "input": {"file_path": "/testbed/pkg/second_source.py"},
                    })
                (rollout_dir / "instance-a.traj.json").write_text(
                    json.dumps(document), encoding="utf-8"
                )

            validation = {
                "runs": [{
                    "scope": "claude-code/model-a",
                    "verdicts": [{
                        "instance_id": "instance-a",
                        "details": {"rollouts": [
                            {"rollout": 1, "passed": True},
                            {"rollout": 2, "passed": True},
                            {"rollout": 3, "passed": False},
                        ]},
                    }],
                }]
            }
            (run_dir / "validation_report.json").write_text(
                json.dumps(validation), encoding="utf-8"
            )
            evaluation = {
                "runs": [{
                    "scope": "kimi/test-model",
                    "verdicts": [{"instance_id": "instance-a", "passed": True}],
                }]
            }
            (run_dir / "evaluation_report.json").write_text(
                json.dumps(evaluation), encoding="utf-8"
            )

            report = build_report(
                [run_dir],
                matched_only=True,
                aggregate_instances=True,
                downstream_evaluation_scope="kimi/test-model",
            )
            self.assertEqual(report["unfiltered_rollout_count"], 3)
            self.assertEqual(report["rollout_count"], 2)
            self.assertEqual(report["excluded_mismatched_rollouts"], 1)
            self.assertEqual(len(report["instances"]), 1)
            instance = report["instances"][0]
            self.assertEqual(instance["matched_rollouts"], 2)
            self.assertEqual(instance["average_observed_effort_score"], 5.0)
            self.assertTrue(instance["downstream_evaluation"]["kimi/test-model"])
            easy = report["downstream_accuracy_by_average_effort_difficulty"][0]
            self.assertEqual((easy["correct"], easy["total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
