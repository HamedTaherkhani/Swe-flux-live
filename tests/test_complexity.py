import json
import tempfile
import unittest
from pathlib import Path

from repogen.complexity import (
    METRICS,
    _answer_score,
    _answer_stats,
    _navigation_score,
    _semantic_score,
    _trace_features,
    assign_difficulties,
    build_report,
    materialize_difficulty_reports,
)
from repogen.validation import agent_validated_instances


class ComplexityScoreTests(unittest.TestCase):
    def test_trace_features_capture_executed_reasoning_burden(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "trace.log"
            trace_path.write_text(
                "\n".join([
                    "2026-01-01 /repo/a.py:10 pkg.f event=call locals={'x': '0'}",
                    "2026-01-01 /repo/a.py:10 pkg.f event=line locals={'x': '1'}",
                    "2026-01-01 /repo/a.py:11 pkg.f event=line locals={}",
                    "2026-01-01 /repo/a.py:10 pkg.f event=line locals={'x': '2'}",
                    "2026-01-01 /repo/a.py:20 pkg.g event=call locals={}",
                    "2026-01-01 /repo/a.py:12 pkg.g event=line locals={}",
                    "2026-01-01 /repo/a.py:12 pkg.g event=return retval=None locals={}",
                    "2026-01-01 /repo/a.py:10 pkg.f event=return retval=None locals={}",
                ]),
                encoding="utf-8",
            )
            features = _trace_features(trace_path)
            self.assertEqual(features["state_change_events"], 2)
            self.assertEqual(features["dynamic_branch_points"], 1)
            self.assertEqual(features["dynamic_branch_alternatives"], 1)
            self.assertEqual(features["max_call_depth"], 2)

    def test_each_score_responds_to_its_own_intrinsic_workload(self):
        small_answer, _ = _answer_score(_answer_stats({"value": 1}))
        large_answer, _ = _answer_score(
            _answer_stats({"values": list(range(80)), "nested": {"text": "x" * 400}})
        )
        self.assertGreater(large_answer, small_answer)

        low_semantic, _ = _semantic_score({}, {})
        high_semantic, _ = _semantic_score(
            {
                "branches": 12,
                "loops": 4,
                "max_loop_nesting": 2,
                "assigns": 20,
                "calls": 15,
                "excepts": 3,
            },
            {
                "distinct_line_transitions": 80,
                "distinct_functions": 8,
                "exception_events": 3,
                "transition_entropy": 0.9,
            },
        )
        self.assertGreater(high_semantic, low_semantic)

        executed_semantic, components = _semantic_score(
            {},
            {
                "line_events": 4000,
                "distinct_lines": 80,
                "max_line_repetition": 900,
                "distinct_line_transitions": 100,
                "dynamic_branch_alternatives": 12,
                "state_change_events": 1000,
                "call_events": 500,
                "distinct_functions": 8,
                "max_call_depth": 12,
                "exception_events": 5,
            },
        )
        self.assertGreater(executed_semantic, low_semantic)
        self.assertGreater(components["execution_workload"], 0)

        sparse, _ = _navigation_score(
            exercise_mode="direct", relevant_files=1, relevant_functions=1,
            test={"imports": 1, "calls": 2, "source_lines": 20}, callers=0,
        )
        well_signposted, _ = _navigation_score(
            exercise_mode="indirect", relevant_files=5, relevant_functions=12,
            test={"imports": 10, "calls": 50, "source_lines": 300}, callers=8,
        )
        self.assertGreater(sparse, well_signposted)

        narrow_execution, _ = _navigation_score(
            exercise_mode="direct", relevant_files=1, relevant_functions=1,
            test={"imports": 1, "calls": 2, "source_lines": 20}, callers=0,
            executed_lines=5,
        )
        broad_execution, components = _navigation_score(
            exercise_mode="direct", relevant_files=1, relevant_functions=1,
            test={"imports": 1, "calls": 2, "source_lines": 20}, callers=0,
            executed_lines=150,
        )
        self.assertGreater(broad_execution, narrow_execution)
        self.assertGreater(components["executed_code_footprint"], 0)

    def test_quantile_bins_are_computed_without_outcomes(self):
        instances = []
        for index, score in enumerate((1.0, 2.0, 3.0, 4.0), start=1):
            instances.append({
                "instance_id": f"i{index}",
                "category": "S2_Loops",
                "answer_archetype": "loop_iteration_count",
                "scores": {metric: score for metric in METRICS},
            })
        assign_difficulties(
            instances,
            easy_quantile=0.25,
            medium_quantile=0.50,
            very_hard_quantile=0.75,
            stratify_by="none",
        )
        for metric in METRICS:
            self.assertEqual(
                [instance["difficulty"][metric] for instance in instances],
                ["easy", "medium", "hard", "very_hard"],
            )

    def test_repository_navigation_uses_global_quartiles_by_default(self):
        instances = []
        for index, (score, archetype) in enumerate(
            ((1.0, "a"), (2.0, "b"), (3.0, "b"), (4.0, "a")), start=1
        ):
            instances.append({
                "instance_id": f"i{index}",
                "category": "S2_Loops",
                "answer_archetype": archetype,
                "scores": {metric: score for metric in METRICS},
            })
        thresholds = assign_difficulties(instances)
        self.assertEqual(thresholds["repository_navigation"]["stratify_by"], "none")
        self.assertEqual(
            [x["difficulty"]["repository_navigation"] for x in instances],
            ["easy", "medium", "hard", "very_hard"],
        )
        self.assertEqual(thresholds["combined"]["stratify_by"], "answer_archetype")


class ComplexityNoLeakTests(unittest.TestCase):
    def _make_run(self, root: Path) -> Path:
        run_dir = root / "repo" / "run_1"
        instance_dir = run_dir / "instances" / "sample_s2_loops"
        files_dir = instance_dir / "files"
        harvest_dir = run_dir / "logs" / instance_dir.name / "harvest"
        files_dir.mkdir(parents=True)
        harvest_dir.mkdir(parents=True)

        oracle = {
            "question_kind": "S2_Loops",
            "question": "Count iterations in `pkg/target.py`.",
            "template_answer": {"loop_iteration_count": "int"},
            "oracle_answer": {"loop_iteration_count": 12},
        }
        (instance_dir / "oracle.json").write_text(json.dumps(oracle), encoding="utf-8")
        (instance_dir / "eval.sh").write_text(
            'export TRACE_FILE="pkg/target.py"\nexport TRACE_FUNC="target"\n',
            encoding="utf-8",
        )
        (files_dir / "testcase.py").write_text(
            "from pkg.target import target\n\ndef test_target():\n    assert target(4)\n",
            encoding="utf-8",
        )
        trace_lines = [
            f"2026-01-01 00:00:00.000 /testbed/pkg/target.py:{10 + i % 4} "
            f"pkg.target event=line locals={{'i': {i}}}"
            for i in range(20)
        ]
        (harvest_dir / "trace.log").write_text("\n".join(trace_lines), encoding="utf-8")
        plan = [{
            "instance_id": instance_dir.name,
            "category": "S2_Loops",
            "exercise_mode": "direct",
            "target": {
                "callers": [],
                "callers_2hop": [],
                "metrics": {"branches": 2, "loops": 1, "assigns": 2, "calls": 1},
            },
        }]
        (run_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (run_dir / "validation_report.json").write_text(
            json.dumps({
                "runs": [{
                    "validator": "solver_agent",
                    "scope": "claude-code/claude-haiku-4-5-20251001",
                    "verdicts": [{
                        "instance_id": instance_dir.name,
                        "passed": True,
                        "details": {"pass_count": 1},
                    }],
                }],
            }),
            encoding="utf-8",
        )
        return run_dir

    def test_cascade_files_do_not_affect_scores_or_bins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._make_run(Path(temp_dir))
            before = build_report([run_dir], stratify_by="none")
            (run_dir / "difficulty_report.json").write_text(
                json.dumps({"assignments": {"sample_s2_loops": {"difficulty": "hard"}}}),
                encoding="utf-8",
            )
            (run_dir / "validation_report.json").write_text(
                json.dumps({"runs": [{"scope": "claude/fable", "passed": 0}]}),
                encoding="utf-8",
            )
            after = build_report([run_dir], stratify_by="none")
            self.assertEqual(before["thresholds"], after["thresholds"])
            self.assertEqual(before["instances"][0]["scores"], after["instances"][0]["scores"])
            self.assertEqual(
                before["instances"][0]["difficulty"], after["instances"][0]["difficulty"]
            )

    def test_evaluation_is_joined_only_after_difficulty_is_fixed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._make_run(Path(temp_dir))

            def write_outcome(passed: bool) -> None:
                report = {
                    "runs": [{
                        "validator": "solver_llm",
                        "scope": "heldout/model",
                        "verdicts": [{"instance_id": "sample_s2_loops", "passed": passed}],
                    }]
                }
                (run_dir / "evaluation_report.json").write_text(
                    json.dumps(report), encoding="utf-8"
                )

            write_outcome(False)
            failed = build_report([run_dir], evaluation_scope="heldout/model", stratify_by="none")
            write_outcome(True)
            passed = build_report([run_dir], evaluation_scope="heldout/model", stratify_by="none")

            self.assertEqual(failed["thresholds"], passed["thresholds"])
            self.assertEqual(failed["instances"][0]["scores"], passed["instances"][0]["scores"])
            self.assertEqual(
                failed["instances"][0]["difficulty"], passed["instances"][0]["difficulty"]
            )
            self.assertFalse(failed["instances"][0]["evaluation"]["heldout/model"])
            self.assertTrue(passed["instances"][0]["evaluation"]["heldout/model"])

    def test_intrinsic_artifacts_replace_and_preserve_legacy_cascade_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._make_run(Path(temp_dir))
            legacy = {
                "tiers": [{"label": "easy", "model": "haiku"}],
                "assignments": {
                    "sample_s2_loops": {"difficulty": "easy", "pass_count": 3}
                },
                "rejected": [],
            }
            (run_dir / "difficulty_report.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            report = build_report([run_dir], stratify_by="none")
            materialize_difficulty_reports(report)

            cascade = json.loads(
                (run_dir / "cascade_validation_report.json").read_text(encoding="utf-8")
            )
            self.assertFalse(cascade["affects_difficulty"])
            self.assertEqual(cascade["purpose"], "solver_validation_only")
            self.assertEqual(
                cascade["assignments"]["sample_s2_loops"]["validation_band"],
                "easy",
            )
            self.assertNotIn(
                "difficulty", cascade["assignments"]["sample_s2_loops"]
            )
            difficulty = json.loads(
                (run_dir / "difficulty_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(difficulty["method"], "intrinsic_complexity")
            assignment = difficulty["assignments"]["sample_s2_loops"]
            self.assertEqual(set(assignment["difficulty"]), set(METRICS))
            per_instance = json.loads(
                (run_dir / "instances" / "sample_s2_loops" / "difficulty.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(per_instance["method"], "intrinsic_complexity")


class ValidationGateTests(unittest.TestCase):
    def test_only_haiku_or_fable_matched_rollouts_validate_an_instance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "validation_report.json").write_text(
                json.dumps({
                    "runs": [
                        {
                            "validator": "solver_agent",
                            "scope": "claude-code/claude-haiku-4-5",
                            "verdicts": [{
                                "instance_id": "haiku_partial",
                                "passed": False,
                                "details": {"pass_count": 1},
                            }],
                        },
                        {
                            "validator": "solver_agent",
                            "scope": "claude-code/claude-fable-5",
                            "verdicts": [{
                                "instance_id": "fable_failed",
                                "passed": False,
                                "details": {"pass_count": 0},
                            }],
                        },
                        {
                            "validator": "solver_agent",
                            "scope": "claude-code/claude-sonnet-4-6",
                            "verdicts": [{
                                "instance_id": "sonnet_passed",
                                "passed": True,
                                "details": {"pass_count": 3},
                            }],
                        },
                    ],
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                agent_validated_instances(run_dir), {"haiku_partial"}
            )


if __name__ == "__main__":
    unittest.main()
