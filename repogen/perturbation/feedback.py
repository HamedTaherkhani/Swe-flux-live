"""Bounded feedback loop for perturbations that miss their hardness target.

A single-shot proposal often lands a variant that runs fine but produces the
same oracle, or walks the exact same execution path -- i.e. it is not actually a
new question. This loop shows the model *why* its last attempt was weak (same
path / unchanged oracle, with both oracle answers) and asks for a stronger one,
up to N iterations per source instance.

Stops early when a candidate reaches the configured combined-complexity target.
The optional target-model flip mode retains its historical pass->fail objective.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .coverage import CoverageSignature
from .pipeline import Attempt, PerturbationPipeline
from .proposer import LLMProposer, ProposerConfig

_SYSTEM_PROMPT = """\
You are strengthening a pytest perturbation that missed its intrinsic \
combined-complexity target. Produce ONE improved variant. Do not optimize \
against downstream outcomes unless the feedback explicitly says that optional \
flip mode is enabled.

Editing policy:
{structure_policy}

Hard rules:
1. The variant must be valid runnable Python that reaches the behaviour under \
test without unrelated errors.
2. Optimize the measured combination using the diagnostic's PRIORITY ORDER and \
submetrics: semantic reasoning 40% (executed branch alternatives, changed-state \
events, call depth, exceptions, and meaningful execution workload), answer \
construction 35% (more leaves, ordered events, useful permitted depth and exact \
detail), and repository navigation 25% (primarily input-activated DISTINCT \
executed source lines and indirect helpers). Every dimension must increase. Do \
not game navigation support by removing clues or test structure.

Output exactly one complete Python test file. No fences, no explanation.
"""

_USER_PROMPT = """\
Target test file: {test_path}
TRACE_FILE: {trace_file}
TRACE_FUNC: {trace_func}

The question this instance asks:
{question}

Feedback on the previous attempt:
- Execution path identical to the original: {same_path}
- Oracle answer changed from the original: {oracle_changed}
- Target model still answered the perturbed instance CORRECTLY: {still_correct}
- Why it was rejected: {reject_reason}
- Source and target intrinsic scorecard:
{complexity_context}
- Previous candidate scores: {candidate_scores}
- Previous score deltas: {complexity_deltas}
- Previous candidate measured submetrics: {candidate_components}
- Previous candidate raw intrinsic evidence: {candidate_features}

Original oracle answer:
{original_oracle}

Previous attempt's oracle answer:
{current_oracle}

----- ORIGINAL TEST FILE -----
{original_source}
----- END ORIGINAL TEST FILE -----

----- PREVIOUS ATTEMPT (improve on this) -----
{current_source}
----- END PREVIOUS ATTEMPT -----
"""


def _compact(value: object, limit: int = 3000) -> str:
    text = json.dumps(value, indent=1, default=str, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def _score(attempt: Attempt) -> tuple:
    """Rank attempts by the active objectives before legacy trace proxies."""
    return (
        int(attempt.flipped is True),
        int(attempt.complexity_target_met is True),
        int(attempt.complexity_increased is True),
        float(attempt.complexity_deltas.get("combined", 0)),
        int(bool(attempt.oracle_changed) and bool(attempt.trace_changed)),
        int(bool(attempt.oracle_changed)),
        int(bool(attempt.trace_changed)),
        attempt.new_lines + attempt.new_edges,
        attempt.new_edges,
    )


class FeedbackRunner:
    """Runs refinement rounds for source instances that yielded nothing good."""

    def __init__(self, pipeline: PerturbationPipeline, iterations: int) -> None:
        self.p = pipeline
        self.iterations = iterations

    def weak_sources(self) -> list[str]:
        """Source instances that produced nothing strong enough.

        Explicit flip mode keeps its pass->fail goal. Otherwise the configured
        intrinsic combined-complexity target is the bar. ``none`` preserves the
        historical oracle-change criterion.
        """
        flip_mode = self.p.config.flip_check and not self.p.infra_aborted
        by_source: dict[str, list[Attempt]] = {}
        for attempt in self.p.attempts:
            by_source.setdefault(attempt.original_id, []).append(attempt)
        weak = []
        for original_id, attempts in by_source.items():
            if flip_mode:
                if any(a.kept and a.flipped for a in attempts):
                    continue
                # The model never solved the original, so there is no flip to win.
                if any(a.model_passed_original is False for a in attempts):
                    continue
            elif self.p.config.complexity_target != "none":
                if any(a.kept and a.complexity_target_met for a in attempts):
                    continue
            elif any(a.kept and a.oracle_changed for a in attempts):
                continue
            weak.append(original_id)
        return sorted(weak)

    def run(self) -> list[Attempt]:
        targets = self.weak_sources()
        if not targets or self.iterations <= 0:
            return []
        self.p._log(
            f"[perturb] feedback: {len(targets)} source(s) with no strong variant, "
            f"up to {self.iterations} iteration(s) each"
        )
        repo_root = self.p.repo_root()
        cfg = self.p.config
        proposer_cfg = ProposerConfig(
            provider=cfg.provider, model=cfg.model, temperature=cfg.temperature,
            reasoning_effort=cfg.reasoning_effort, n=1,
            max_read_lines=cfg.max_read_lines, repo_map_mode=cfg.repo_map_mode,
            enforce_structure=cfg.enforce_structure,
        )
        produced: list[Attempt] = []

        for original_id in targets:
            produced.extend(self._run_one(original_id, proposer_cfg, repo_root))
            self.p.write_report()
        return produced

    def _run_one(self, original_id: str, proposer_cfg: ProposerConfig, repo_root: Path) -> list[Attempt]:
        test_path = self.p.source_instances / original_id / "files" / "testcase.py"
        try:
            original_source = test_path.read_text(encoding="utf-8")
        except OSError:
            return []

        prior = [a for a in self.p.attempts if a.original_id == original_id]
        best = max(prior, key=_score) if prior else None
        current_source = original_source
        current_oracle: object = None
        if best is not None and best.kept:
            candidate_test = self.p.output_instances / best.new_id / "files" / "testcase.py"
            if candidate_test.is_file():
                current_source = candidate_test.read_text(encoding="utf-8")
                current_oracle = self.p._oracle(best.new_id, base=self.p.output_instances).get("oracle_answer")

        baseline = self.p._baseline_coverage(original_id)
        trace_file, trace_funcs = self.p._trace_targets(original_id)
        oracle = self.p._oracle(original_id)
        produced: list[Attempt] = []

        for iteration in range(self.iterations):
            reject_reason = (best.detail if best is not None else "no candidate survived harvest")
            user_prompt = _USER_PROMPT.format(
                test_path=str(test_path.relative_to(self.p.source_instances)),
                trace_file=trace_file or "(not set)",
                trace_func=", ".join(trace_funcs) or "(not set)",
                question=str(oracle.get("question", ""))[:4000],
                same_path=best.same_path_as_original if best else "unknown",
                oracle_changed=best.oracle_changed if best else "unknown",
                still_correct=(best.model_passed_perturbed if best else None)
                if best is not None else "unknown",
                reject_reason=(reject_reason or "")[:300],
                complexity_context=self.p.complexity_context(original_id),
                candidate_scores=_compact(best.candidate_complexity_scores)
                if best is not None else "(none)",
                complexity_deltas=_compact(best.complexity_deltas)
                if best is not None else "(none)",
                candidate_components=_compact(best.candidate_complexity_components)
                if best is not None else "(none)",
                candidate_features=_compact(best.candidate_complexity_features)
                if best is not None else "(none)",
                original_oracle=_compact(oracle.get("oracle_answer")),
                current_oracle=_compact(current_oracle) if current_oracle is not None else "(none harvested)",
                original_source=original_source,
                current_source=current_source,
            )
            proposer = LLMProposer(proposer_cfg)
            structure_policy = (
                "Change only input values and preserve imports, definitions, statements, "
                "calls, and assertions exactly."
                if self.p.config.enforce_structure else
                "REQUIRED INPUT-ONLY EDIT: change literal/data values, collection "
                "contents and sizes, nested structures, constructor data, and keyword "
                "values. Do not add/remove imports, definitions, statements, calls, "
                "assertions, loops, or helper code. Hardness must come from inputs."
            )
            variants = proposer.propose(
                original_source=original_source,
                test_rel_path=str(test_path.relative_to(self.p.source_instances)),
                trace_file=trace_file, trace_funcs=trace_funcs,
                question=str(oracle.get("question", "")),
                repo_root=repo_root,
                instance_dir=self.p.source_instances / original_id,
                n=1,
                system_prompt=_SYSTEM_PROMPT.format(structure_policy=structure_policy),
                user_prompt=user_prompt,
            )
            if not variants:
                self.p._log(f"    fb i{iteration} {original_id}: no valid proposal")
                continue

            new_id = self.p.config.feedback_instance_id(original_id, iteration)
            attempt = self.p.evaluate_candidate(
                original_id, new_id, variants[0], -1, baseline, feedback_iteration=iteration
            )
            self.p.attempts.append(attempt)
            produced.append(attempt)
            self.p._log(f"    fb i{iteration} {self.p._fmt(attempt)}")

            strong = (
                attempt.kept and attempt.flipped
                if (self.p.config.flip_check and not self.p.infra_aborted)
                else (
                    attempt.kept and attempt.complexity_target_met
                    if self.p.config.complexity_target != "none"
                    else attempt.kept and attempt.oracle_changed
                )
            )
            if strong:
                break  # strong enough; stop refining this source
            if self.p.infra_aborted:
                self.p._log("    fb: provider refused; stopping the feedback loop")
                break
            best = attempt if (best is None or _score(attempt) > _score(best)) else best
            if attempt.kept:
                current_source = variants[0]
                current_oracle = self.p._oracle(new_id, base=self.p.output_instances).get("oracle_answer")
        return produced
