import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repogen.perturbation.config import PerturbationConfig
from repogen.perturbation.pipeline import Attempt, PerturbationPipeline
from repogen.perturbation.proposer import LLMProposer, ProposerConfig


class PerturbationComplexityTests(unittest.TestCase):
    def _make_run(self, root: Path) -> tuple[Path, Path]:
        run_dir = root / "repo" / "run_1"
        instances = run_dir / "instances"
        ids = (
            "easy_validated",
            "easy_unvalidated",
            "hard_validated",
            "easy_rejected",
        )
        for instance_id in ids:
            instance_dir = instances / instance_id
            (instance_dir / "files").mkdir(parents=True)
            (instance_dir / "oracle.json").write_text(
                json.dumps({
                    "question_kind": "S2_Loops",
                    "question": "How many iterations?",
                    "oracle_answer": {"loop_iteration_count": 2},
                }),
                encoding="utf-8",
            )
            (instance_dir / "files" / "testcase.py").write_text(
                "def test_value():\n    assert True\n", encoding="utf-8"
            )

        (run_dir / "validation_report.json").write_text(
            json.dumps({
                "runs": [{
                    "validator": "solver_agent",
                    "scope": "claude-code/claude-haiku-4-5-20251001",
                    "verdicts": [
                        {
                            "instance_id": "easy_validated",
                            "passed": False,
                            "details": {"pass_count": 1},
                        },
                        {
                            "instance_id": "easy_unvalidated",
                            "passed": False,
                            "details": {"pass_count": 0},
                        },
                        {"instance_id": "hard_validated", "passed": True},
                        {"instance_id": "easy_rejected", "passed": True},
                    ],
                }]
            }),
            encoding="utf-8",
        )
        (run_dir / "difficulty_report.json").write_text(
            json.dumps({"rejected": ["easy_rejected"]}), encoding="utf-8"
        )

        records = []
        for instance_id in ids:
            easy = instance_id != "hard_validated"
            records.append({
                "run_dir": str(run_dir),
                "instance_id": instance_id,
                "category": "S2_Loops",
                "answer_archetype": "loop_iteration_count",
                "scores": {
                    "semantic_reasoning": 3.0,
                    "answer_construction": 2.0,
                    "repository_navigation": 4.0,
                    "combined": 3.0 if easy else 8.0,
                },
                "components": {
                    "semantic_reasoning": {
                        "control_flow": 3.0,
                        "state_tracking": 2.0,
                        "interprocedural": 4.0,
                        "exception_semantics": 1.0,
                        "execution_workload": 3.5,
                    },
                    "answer_construction": {
                        "answer_volume": 2.0,
                        "ordered_output": 1.0,
                        "structural_depth": 4.0,
                        "exact_value_precision": 2.5,
                    },
                    "repository_navigation": {
                        "executed_code_footprint": 2.0,
                        "navigation_uncertainty": 6.0,
                        "weighted_navigation_support": 4.0,
                    },
                },
                "features": {
                    "trace": {
                        "dynamic_branch_alternatives": 2,
                        "state_change_events": 10,
                        "max_call_depth": 2,
                        "line_events": 50,
                        "distinct_lines": 12,
                    },
                    "answer": {
                        "leaf_count": 2,
                        "ordered_element_count": 1,
                        "max_depth": 3,
                    },
                    "navigation": {
                        "exercise_mode": "direct",
                        "distinct_executed_lines": 12,
                    },
                },
                "difficulty": {
                    metric: "easy" if easy else "hard"
                    for metric in (
                        "semantic_reasoning",
                        "answer_construction",
                        "repository_navigation",
                        "combined",
                    )
                },
            })
        complexity_report = root / "complexity_report.json"
        complexity_report.write_text(
            json.dumps({
                "instances": records,
                "thresholds": {
                    metric: {
                        "stratify_by": "answer_archetype",
                        "strata": {
                            "loop_iteration_count": {
                                "instances": 4,
                                "easy_max_score": 4.0,
                                "medium_max_score": 5.5,
                                "very_hard_min_score": 7.0,
                            }
                        },
                    }
                    for metric in (
                        "semantic_reasoning",
                        "answer_construction",
                        "repository_navigation",
                        "combined",
                    )
                },
            }),
            encoding="utf-8",
        )
        return run_dir, complexity_report

    def test_default_pool_is_validated_combined_easy_and_not_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, report = self._make_run(Path(temp_dir))
            pipeline = PerturbationPipeline(PerturbationConfig(
                run_dir=run_dir,
                repo_key="repo",
                image="image",
                complexity_report=report,
                progress=False,
            ))
            self.assertEqual(pipeline.output_root, Path(temp_dir) / "perturbation")
            self.assertEqual(pipeline._instance_ids(), ["easy_validated"])

    def test_candidate_must_increase_and_leave_easy_bin_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, report = self._make_run(Path(temp_dir))
            pipeline = PerturbationPipeline(PerturbationConfig(
                run_dir=run_dir,
                repo_key="repo",
                image="image",
                complexity_report=report,
                progress=False,
            ))
            attempt = Attempt("easy_validated", "candidate", 0)
            candidate = {
                "category": "S2_Loops",
                "answer_archetype": "loop_iteration_count",
                "scores": {
                    "semantic_reasoning": 6.0,
                    "answer_construction": 5.0,
                    "repository_navigation": 5.0,
                    "combined": 5.0,
                },
            }
            with patch("repogen.perturbation.pipeline.extract_instance", return_value=candidate):
                pipeline._measure_candidate_complexity(
                    attempt, "easy_validated", run_dir / "instances" / "easy_validated"
                )
            self.assertEqual(attempt.candidate_complexity_difficulty, "medium")
            self.assertEqual(
                attempt.candidate_complexity_difficulties,
                {
                    "semantic_reasoning": "hard",
                    "answer_construction": "medium",
                    "repository_navigation": "medium",
                    "combined": "medium",
                },
            )
            self.assertTrue(attempt.complexity_increased)
            self.assertTrue(attempt.complexity_target_met)

    def test_prompt_diagnosis_prioritizes_easy_metrics_and_explains_submetrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, report = self._make_run(Path(temp_dir))
            pipeline = PerturbationPipeline(PerturbationConfig(
                run_dir=run_dir,
                repo_key="repo",
                image="image",
                complexity_report=report,
                progress=False,
            ))
            context = pipeline.complexity_context("easy_validated")
            self.assertIn("PRIORITY 1: ANSWER CONSTRUCTION — EASY", context)
            self.assertIn("answer_volume=2.0", context)
            self.assertIn("make the existing parser emit more answer leaves", context)
            self.assertIn("execution_workload=3.5", context)
            self.assertIn("executed_code_footprint=2.0", context)
            self.assertIn("Next goal: score > 4.0 to leave EASY", context)
            self.assertIn("Change test INPUT DATA only", context)

    def test_downstream_flip_mode_remains_opt_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, report = self._make_run(Path(temp_dir))
            config = PerturbationConfig(
                run_dir=run_dir,
                repo_key="repo",
                image="image",
                complexity_report=report,
            )
            self.assertFalse(config.flip_check)
            self.assertFalse(config.require_flip)
            self.assertEqual(config.source_selection, "validated-easy")
            self.assertEqual(config.complexity_target, "medium")
            self.assertFalse(config.enforce_structure)

    def test_structure_check_is_retained_but_opt_in(self):
        original = "def test_value():\n    return len([1])\n"
        changed_calls = "def test_value():\n    return sum([len([1]), 2])\n"
        relaxed = LLMProposer(ProposerConfig(enforce_structure=False))
        strict = LLMProposer(ProposerConfig(enforce_structure=True))
        self.assertEqual(
            relaxed.parse_variants(changed_calls, original, 1),
            [changed_calls.strip()],
        )
        self.assertEqual(strict.parse_variants(changed_calls, original, 1), [])


if __name__ == "__main__":
    unittest.main()
