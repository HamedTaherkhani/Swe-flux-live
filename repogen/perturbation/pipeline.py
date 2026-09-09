"""Orchestrates propose -> materialize -> harvest -> screen for perturbations.

Output is written as a normal repogen run directory (instances/ + the harness
scripts + shared/), so `repogen screen`, `repogen cascade` and `repogen evaluate`
work on the perturbed set with no special-casing.

Proposal calls are threaded (they are pure API work); harvesting is serialized by
default because each harvest starts a container, though a unique container name
per worker makes limited concurrency safe.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as _dt
import queue
import json
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ..complexity import (
    METRICS as COMPLEXITY_METRICS,
    _plan_entries,
    _screen_indirection,
    extract_instance,
)
from ..docker_env import Container
from ..screening import DEFAULT_RULES, InstanceContext
from .config import PerturbationConfig
from .coverage import CoverageExtractor, CoverageSignature
from .flip import FlipChecker, FlipVerdict, original_verdicts
from .harvest import OracleHarvester
from .materializer import InstanceMaterializer
from .proposer import LLMProposer, ProposerConfig

NON_INSTANCE_DIRS = {"shared", "qa_artifacts"}
HARNESS_FILES = ("qa_pipeline.sh", "run_qa_fromhost.sh", "run_all_qa_fromhost.sh")

_DIFFICULTY_RANK = {"unknown": -1, "easy": 0, "medium": 1, "hard": 2, "very_hard": 3}
_METRIC_TITLES = {
    "semantic_reasoning": "SEMANTIC REASONING",
    "answer_construction": "ANSWER CONSTRUCTION",
    "repository_navigation": "REPOSITORY NAVIGATION",
}
_METRIC_WEIGHTS = {
    "semantic_reasoning": 0.40,
    "answer_construction": 0.35,
    "repository_navigation": 0.25,
}
_COMPONENT_ACTIONS = {
    "semantic_reasoning": {
        "control_flow": (
            "RAISE: choose heterogeneous valid values that take different existing "
            "branch successors in one run, especially below/at/above real thresholds."
        ),
        "state_tracking": (
            "RAISE: make target locals or repository objects evolve through varied "
            "updates/mutations across iterations and calls; test-side assignments do not count."
        ),
        "interprocedural": (
            "RAISE: select supported modes/types/keys that activate existing dispatch, "
            "callbacks, recursion, and deeper helper-call chains."
        ),
        "exception_semantics": (
            "RAISE when supported: enter handled exception, fallback, retry, or recovery "
            "paths while the test still passes; unrelated crashes are invalid."
        ),
        "execution_workload": (
            "RAISE: increase meaningful traced line events, distinct lines, calls, and "
            "state-varying repetition. Repeating an unchanged path is weak."
        ),
        "dynamic_diversity": (
            "RAISE (legacy): execute more distinct transitions/functions and varied paths."
        ),
    },
    "answer_construction": {
        "answer_volume": (
            "RAISE: use inputs that make the existing parser emit more answer leaves/records."
        ),
        "ordered_output": (
            "RAISE: produce longer ordered histories, paths, events, or call records with "
            "meaningfully different elements."
        ),
        "structural_depth": (
            "SCHEMA-BOUND: populate existing nested/list fields more richly when possible; "
            "never change the canonical answer schema or parser contract."
        ),
        "exact_value_precision": (
            "RAISE: cause the answer to contain more varied exact strings and numeric values, "
            "not merely one inflated scalar."
        ),
    },
    "repository_navigation": {
        "executed_code_footprint": (
            "PRIMARY ACTIONABLE LEVER—RAISE: through input data, execute more DISTINCT "
            "repository source lines and valid indirect/helper paths."
        ),
        "navigation_uncertainty": (
            "HIGHER IS HARDER, but raise it only through genuine runtime behavior; never "
            "remove question clues or obscure the test."
        ),
        "weighted_navigation_support": (
            "INVERSE DIAGNOSTIC: higher support makes navigation easier. Do not game it by "
            "removing imports, paths, symbols, or rewriting test structure."
        ),
        "entrypoint_support": "CONTEXT ONLY under input-only editing; do not manipulate it.",
        "explicit_file_clues": "CONTEXT ONLY; do not delete or hide file clues.",
        "explicit_function_clues": "CONTEXT ONLY; do not delete or hide function clues.",
        "test_context": "CONTEXT ONLY; do not reduce test readability or remove calls.",
        "api_centrality": "CONTEXT ONLY; prefer real input-selected dispatch paths.",
    },
}
_RAW_FEATURE_KEYS = {
    "semantic_reasoning": (
        "dynamic_branch_points", "dynamic_branch_alternatives",
        "state_change_events", "max_call_depth", "line_events",
        "distinct_lines", "distinct_line_transitions", "call_events",
        "distinct_functions", "exception_events", "max_line_repetition",
    ),
    "answer_construction": (
        "leaf_count", "ordered_element_count", "max_list_length", "max_depth",
        "string_characters", "numeric_digits",
    ),
    "repository_navigation": (
        "exercise_mode", "relevant_file_count", "relevant_function_count",
        "known_callers", "distinct_executed_lines", "source_lines", "imports", "calls",
    ),
}


@dataclass
class Attempt:
    original_id: str
    new_id: str
    variant_index: int
    category: str = ""
    kept: bool = False
    stage: str = ""
    detail: str = ""
    oracle_changed: Optional[bool] = None
    trace_changed: Optional[bool] = None
    same_path_as_original: Optional[bool] = None
    new_lines: int = 0
    new_edges: int = 0
    # Execution size, recorded for EVERY attempt (kept or dropped) so prompt
    # changes aimed at lengthening execution can be measured even on candidates
    # that were later discarded.
    trace_line_events: int = 0
    baseline_line_events: int = 0
    trace_ratio: float = 0.0
    source_complexity_scores: dict = field(default_factory=dict)
    candidate_complexity_scores: dict = field(default_factory=dict)
    candidate_complexity_components: dict = field(default_factory=dict)
    candidate_complexity_features: dict = field(default_factory=dict)
    complexity_deltas: dict = field(default_factory=dict)
    source_complexity_difficulties: dict = field(default_factory=dict)
    candidate_complexity_difficulties: dict = field(default_factory=dict)
    # Combined-label aliases retained in reports for compatibility with older
    # perturbation analysis scripts.
    source_complexity_difficulty: str = ""
    candidate_complexity_difficulty: str = ""
    complexity_increased: Optional[bool] = None
    all_complexity_metrics_increased: Optional[bool] = None
    complexity_target_met: Optional[bool] = None
    screening_failures: list = field(default_factory=list)
    feedback_iteration: Optional[int] = None
    # flip stage
    model_passed_original: Optional[bool] = None
    model_passed_perturbed: Optional[bool] = None
    flipped: Optional[bool] = None
    flip_detail: str = ""
    flip_infra_error: str = ""
    flip_cost_usd: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class PerturbationPipeline:
    def __init__(self, config: PerturbationConfig) -> None:
        self.config = config
        self.source_instances = config.run_dir / "instances"
        self.output_root = config.output_root or self._default_output_root()
        self.output_instances = self.output_root / "instances"
        self.materializer = InstanceMaterializer(self.source_instances, self.output_instances)
        self.harvester = OracleHarvester(
            self.output_instances, image=config.image, timeout=config.harvest_timeout
        )
        self.extractor = CoverageExtractor()
        self.attempts: list[Attempt] = []
        self._lock = threading.Lock()
        self._repo_root: Optional[Path] = None
        self._flip_checker: Optional[FlipChecker] = None
        # Pass/fail of the ORIGINAL instances for the target model. Populated
        # from the source run's evaluation report, extended on demand.
        self._baseline_verdicts: dict = {}
        self._complexity_document = self._read_json(config.complexity_report, {})
        self._source_complexity = self._index_source_complexity()
        self._complexity_thresholds = self._complexity_document.get("thresholds", {})
        self._source_plan = _plan_entries(config.run_dir)
        self._source_screen_modes = _screen_indirection(config.run_dir)
        self._selected_source_ids: list[str] = []
        self.infra_aborted = False

    @staticmethod
    def _read_json(path: Optional[Path], default: object) -> object:
        if path is None:
            return default
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return default

    def _index_source_complexity(self) -> dict[str, dict]:
        """Complexity records belonging to this source run, keyed by id."""
        source = self.config.run_dir.resolve()
        indexed: dict[str, dict] = {}
        for record in self._complexity_document.get("instances", []):
            if not isinstance(record, dict) or not record.get("instance_id"):
                continue
            raw_run = record.get("run_dir", "")
            try:
                record_run = Path(raw_run).resolve()
            except (OSError, TypeError):
                continue
            if record_run == source:
                indexed[str(record["instance_id"])] = record
        return indexed

    # -- setup -----------------------------------------------------------------
    def _default_output_root(self) -> Path:
        # Standard runs live at out/<repo>/run_<timestamp>; perturbations pool
        # under out/perturbation unless the caller provides an explicit path.
        return self.config.run_dir.parent.parent / "perturbation"

    def _log(self, msg: str) -> None:
        if self.config.progress:
            print(msg, flush=True)

    def prepare_output(self) -> None:
        """Make the output tree a valid run dir the rest of repogen can consume."""
        self.output_instances.mkdir(parents=True, exist_ok=True)
        for name in HARNESS_FILES:
            src = self.source_instances / name
            if src.is_file():
                shutil.copy2(src, self.output_instances / name)
        shared_src = self.source_instances / "shared"
        shared_dest = self.output_instances / "shared"
        if shared_src.is_dir() and not shared_dest.exists():
            shutil.copytree(shared_src, shared_dest)
        # run_config.json lets `repogen screen/cascade/evaluate --run-dir` resolve
        # the repo and image without being told again.
        src_cfg = self.config.run_dir / "run_config.json"
        cfg = {}
        if src_cfg.is_file():
            try:
                cfg = json.loads(src_cfg.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cfg = {}
        # `repo_key` / `image` are what ValidationContext.from_run_dir reads;
        # without them cascade/evaluate cannot resolve this as a run dir.
        cfg.update({
            "repo_key": self.config.repo_key,
            "repo": self.config.repo_key,
            "image": self.config.image,
            "perturbed_from": str(self.config.run_dir),
            "proposer": {
                "provider": self.config.provider,
                "model": self.config.model,
                "variants": self.config.variants,
            },
            "complexity_objective": {
                "source_selection": self.config.source_selection,
                "target": self.config.complexity_target,
                "keep_below_target": self.config.keep_below_complexity_target,
                "require_all_metric_increases": self.config.require_all_metric_increases,
                "report": str(self.config.complexity_report)
                if self.config.complexity_report else None,
                "combined_weights": {
                    "semantic_reasoning": 0.40,
                    "answer_construction": 0.35,
                    "repository_navigation": 0.25,
                },
            },
        })
        (self.output_root / "run_config.json").write_text(
            json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
        )

    # -- instance metadata -----------------------------------------------------
    def _instance_ids(self) -> list[str]:
        ids = [
            p.name
            for p in sorted(self.source_instances.iterdir())
            if p.is_dir() and p.name not in NON_INSTANCE_DIRS and (p / "oracle.json").is_file()
        ]
        if self.config.instance_ids:
            wanted = set(self.config.instance_ids)
            ids = [i for i in ids if i in wanted]
        ids = self._exclude_reported_instances(ids)
        if self.config.source_selection in {"validated-easy", "easy"}:
            if not self._source_complexity:
                raise ValueError(
                    "intrinsic source selection needs a complexity report containing "
                    f"records for {self.config.run_dir}; run `repogen complexity` or "
                    "pass --complexity-report"
                )
            easy = {
                instance_id for instance_id, record in self._source_complexity.items()
                if record.get("difficulty", {}).get("combined") == "easy"
            }
            before = len(ids)
            ids = [instance_id for instance_id in ids if instance_id in easy]
            self._log(
                f"[perturb] combined-easy source filter: {len(ids)}/{before} "
                "current, non-excluded instance(s)"
            )
        if self.config.source_selection == "validated-easy":
            validated = self._validated_instances()
            if validated is None:
                raise ValueError(
                    "validated-easy source selection needs solver-agent outcomes in "
                    f"{self.config.run_dir / 'validation_report.json'}"
                )
            before = len(ids)
            ids = [instance_id for instance_id in ids if instance_id in validated]
            self._log(
                f"[perturb] solver-validated source filter: {len(ids)}/{before} "
                "combined-easy instance(s) have a matched Haiku/Fable rollout"
            )
        if self.config.only_passing:
            passing = self._passing_instances()
            if passing is not None:
                ids = [i for i in ids if i in passing]
        if self.config.sample_per_category:
            ids = self._sample_by_category(ids, self.config.sample_per_category)
        if self.config.max_instances:
            ids = ids[: self.config.max_instances]
        self._selected_source_ids = list(ids)
        return ids

    def _exclude_reported_instances(self, ids: list[str]) -> list[str]:
        """Honor cascade/manual exclusions even when a no-discard run kept files."""
        reports = [
            self._read_json(
                self.config.run_dir / "cascade_validation_report.json", {}
            ),
            # Compatibility with runs created before cascade became
            # validation-only and stopped owning difficulty_report.json.
            self._read_json(self.config.run_dir / "difficulty_report.json", {}),
        ]
        excluded: set[str] = set()
        for report in reports:
            excluded.update(report.get("rejected", []) or [])
            excluded.update(report.get("manually_excluded", []) or [])
        if not excluded:
            return ids
        kept = [instance_id for instance_id in ids if instance_id not in excluded]
        self._log(
            f"[perturb] excluded-instance filter: removed {len(ids) - len(kept)} "
            "cascade/manual rejection(s)"
        )
        return kept

    def _validated_instances(self) -> Optional[set[str]]:
        """Instances solved by at least one Haiku or Fable rollout."""
        from ..validation import agent_validated_instances

        return agent_validated_instances(self.config.run_dir)

    def _passing_instances(self) -> Optional[set]:
        """Instances the TARGET model already answers correctly, if known.

        Scope matters: a run may hold verdicts from several models, and
        "already passing" is only meaningful for the model whose flip we are
        trying to cause. Unioning across models would select instances the
        target has never solved, where no flip is possible.
        """
        report = self.config.run_dir / "evaluation_report.json"
        if not report.is_file():
            self._log("[perturb] no evaluation_report.json; --only-passing ignored")
            return None
        verdicts = original_verdicts(
            self.config.run_dir, self.config.flip_provider, self.config.flip_model
        )
        if not verdicts:
            self._log(
                f"[perturb] evaluation_report.json has no verdicts for "
                f"{self.config.flip_provider}/{self.config.flip_model}; "
                f"--only-passing ignored"
            )
            return None
        passing = {i for i, ok in verdicts.items() if ok}
        self._log(
            f"[perturb] --only-passing: {len(passing)} instance(s) the target "
            f"model answered correctly"
        )
        return passing

    def _sample_by_category(self, ids: list[str], per_category: int) -> list[str]:
        buckets: dict[str, list[str]] = {}
        for instance_id in ids:
            buckets.setdefault(self._category(instance_id), []).append(instance_id)
        out: list[str] = []
        for _, members in sorted(buckets.items()):
            out.extend(members[:per_category])
        return sorted(out)

    def _oracle(self, instance_id: str, base: Optional[Path] = None) -> dict:
        path = (base or self.source_instances) / instance_id / "oracle.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _category(self, instance_id: str) -> str:
        return str(self._oracle(instance_id).get("question_kind", "")) or "unknown"

    def _trace_targets(self, instance_id: str) -> tuple[str, list[str]]:
        """Read TRACE_FILE / TRACE_FUNC out of the instance's eval.sh."""
        path = self.source_instances / instance_id / "eval.sh"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return "", []
        trace_file = ""
        funcs: list[str] = []
        m = re.search(r'^export TRACE_FILE="([^"]*)"', text, re.MULTILINE)
        if m:
            trace_file = m.group(1)
        m = re.search(r'^export TRACE_FUNC="([^"]*)"', text, re.MULTILINE)
        if m:
            funcs = [f.strip() for f in m.group(1).split(",") if f.strip()]
        return trace_file, funcs

    def _trace_budget(self, sig: CoverageSignature) -> str:
        """Human-readable execution size of the original, for the proposer."""
        if not sig:
            return "(no baseline trace available)"
        line_events = sum(1 for e in sig.events if e[3] == "line")
        calls = sum(1 for e in sig.events if e[3] == "call")
        distinct = len(sig.lines)
        repeat = line_events / max(1, distinct)
        return (
            f"  {line_events} line events, {calls} call events, "
            f"{distinct} distinct lines "
            f"(each line runs {repeat:.1f}x on average)"
        )

    def _complexity_stratum_name(
        self, record: dict, metric_name: str = "combined",
    ) -> str:
        metric = self._complexity_thresholds.get(metric_name, {})
        stratify_by = metric.get("stratify_by", "answer_archetype")
        if stratify_by == "category":
            return str(record.get("category", ""))
        elif stratify_by == "category_archetype":
            return f"{record.get('category', '')}:{record.get('answer_archetype', '')}"
        elif stratify_by == "none":
            return "all"
        return str(record.get("answer_archetype", ""))

    def _complexity_stratum(
        self, record: dict, metric_name: str = "combined",
    ) -> Optional[dict]:
        metric = self._complexity_thresholds.get(metric_name, {})
        name = self._complexity_stratum_name(record, metric_name)
        return metric.get("strata", {}).get(name)

    def _complexity_label(self, record: dict, metric_name: str = "combined") -> str:
        threshold = self._complexity_stratum(record, metric_name)
        if not threshold:
            return "unknown"
        score = float(record.get("scores", {}).get(metric_name, 0))
        if int(threshold.get("instances", 0)) == 1:
            return "medium"
        if score <= float(threshold["easy_max_score"]):
            return "easy"
        # Schema v2 intrinsic reports use four quartile levels. Keep support for
        # legacy three-level reports so interrupted perturbation runs can resume.
        if "medium_max_score" in threshold and "very_hard_min_score" in threshold:
            if score <= float(threshold["medium_max_score"]):
                return "medium"
            if score >= float(threshold["very_hard_min_score"]):
                return "very_hard"
            return "hard"
        if score >= float(threshold["hard_min_score"]):
            return "hard"
        return "medium"

    def complexity_context(self, instance_id: str) -> str:
        """Prioritized, actionable intrinsic diagnosis embedded in every prompt."""
        record = self._source_complexity.get(instance_id, {})
        if not record:
            return (
                "No frozen intrinsic scorecard is available. Increase genuine "
                "control-flow, answer, and navigation complexity while keeping "
                "the runtime question meaningful."
            )
        scores = record.get("scores", {})
        difficulties = record.get("difficulty", {})
        if not isinstance(difficulties, dict):
            difficulties = {"combined": str(difficulties)}
        components = record.get("components", {})
        features = record.get("features", {})

        def metric_label(metric: str) -> str:
            return str(difficulties.get(metric) or self._complexity_label(record, metric))

        def boundary_guidance(metric: str, label: str) -> str:
            threshold = self._complexity_stratum(record, metric) or {}
            if not threshold:
                return "No frozen boundary is available; increase the score without regression."
            easy_max = threshold.get("easy_max_score")
            medium_max = threshold.get("medium_max_score")
            very_hard_min = threshold.get(
                "very_hard_min_score", threshold.get("hard_min_score")
            )
            if label == "easy":
                return f"Next goal: score > {easy_max} to leave EASY."
            if label == "medium" and medium_max is not None:
                return f"Next goal: score > {medium_max} to leave MEDIUM."
            if label == "hard" and very_hard_min is not None:
                return f"Next goal: score >= {very_hard_min} to reach VERY_HARD."
            if label == "very_hard":
                return "Already VERY_HARD: preserve this metric and still increase its raw score."
            return (
                f"Frozen boundaries: easy <= {easy_max}; medium <= {medium_max}; "
                f"very_hard >= {very_hard_min}."
            )

        metric_names = [metric for metric in COMPLEXITY_METRICS if metric != "combined"]
        priority = sorted(
            metric_names,
            key=lambda metric: (
                _DIFFICULTY_RANK.get(metric_label(metric), -1),
                float(scores.get(metric, 0) or 0),
            ),
        )
        combined_label = metric_label("combined")
        combined_threshold = self._complexity_stratum(record, "combined") or {}
        lines = [
            "INTRINSIC DIFFICULTY DIAGNOSIS (higher metric scores are harder)",
            f"Combined: {combined_label.upper()} score={scores.get('combined')}; "
            f"requested candidate target={self.config.complexity_target}.",
            "Combined weights: semantic reasoning 40%; answer construction 35%; "
            "repository navigation 25%.",
            (
                "Combined frozen boundaries: "
                f"easy <= {combined_threshold.get('easy_max_score', 'unknown')}; "
                f"medium <= {combined_threshold.get('medium_max_score', 'unknown')}; "
                f"very_hard >= {combined_threshold.get('very_hard_min_score', 'unknown')} "
                f"(stratum={self._complexity_stratum_name(record, 'combined')})."
            ),
            "",
            "PRIORITY ORDER—work hardest on the easiest metric(s), but every metric "
            "must increase:",
        ]
        for index, metric in enumerate(priority, start=1):
            lines.append(
                f"{index}. {_METRIC_TITLES[metric]}: {metric_label(metric).upper()} "
                f"score={scores.get(metric)} (combined weight "
                f"{_METRIC_WEIGHTS[metric]:.0%})."
            )

        for index, metric in enumerate(priority, start=1):
            label = metric_label(metric)
            threshold = self._complexity_stratum(record, metric) or {}
            lines.extend([
                "",
                f"PRIORITY {index}: {_METRIC_TITLES[metric]} — "
                f"{label.upper()} score={scores.get(metric)}",
                boundary_guidance(metric, label),
                (
                    "Metric boundaries: "
                    f"easy <= {threshold.get('easy_max_score', 'unknown')}; "
                    f"medium <= {threshold.get('medium_max_score', 'unknown')}; "
                    f"very_hard >= {threshold.get('very_hard_min_score', 'unknown')} "
                    f"(stratum={self._complexity_stratum_name(record, metric)})."
                ),
                "Measured submetrics and exact input levers:",
            ])
            metric_components = components.get(metric, {})
            actions = _COMPONENT_ACTIONS[metric]
            for component, value in metric_components.items():
                lines.append(
                    f"  - {component}={value}: "
                    f"{actions.get(component, 'RAISE through genuine input-driven runtime work.')}"
                )
            raw_group = {
                "semantic_reasoning": features.get("trace", {}),
                "answer_construction": features.get("answer", {}),
                "repository_navigation": features.get("navigation", {}),
            }[metric]
            raw = {
                key: raw_group.get(key)
                for key in _RAW_FEATURE_KEYS[metric]
                if key in raw_group
            }
            lines.append(
                "Current raw evidence (increase the actionable counts): "
                + json.dumps(raw, sort_keys=True, default=str)
            )

        lines.extend([
            "",
            "MANDATORY DECISION RULE:",
            "- Before editing, privately identify the lowest actionable submetric in each "
            "priority metric and the repository branch/loop/dispatch behavior that input "
            "data can activate.",
            "- Change test INPUT DATA only. Do not add test loops/helpers/calls, alter the "
            "question/parser/schema, remove navigation clues, or inflate test scaffolding.",
            "- Do not improve only the combined average: preserve stronger metrics and make "
            "all three metric scores increase after re-harvesting.",
        ])
        return "\n".join(lines)

    def _measure_candidate_complexity(
        self, attempt: Attempt, original_id: str, instance_dir: Path,
    ) -> None:
        source = self._source_complexity.get(original_id)
        if not source:
            attempt.complexity_target_met = self.config.complexity_target == "none"
            return
        candidate = extract_instance(
            self.output_root,
            instance_dir,
            plan_entry=self._source_plan.get(original_id, {}),
            screen_mode=self._source_screen_modes.get(original_id, ""),
        )
        attempt.source_complexity_scores = dict(source.get("scores", {}))
        attempt.source_complexity_difficulties = dict(source.get("difficulty", {}))
        attempt.source_complexity_difficulty = str(
            attempt.source_complexity_difficulties.get("combined", "")
        )
        if candidate is None:
            attempt.complexity_target_met = False
            return
        attempt.candidate_complexity_scores = dict(candidate.get("scores", {}))
        attempt.candidate_complexity_components = dict(candidate.get("components", {}))
        attempt.candidate_complexity_features = dict(candidate.get("features", {}))
        attempt.complexity_deltas = {
            metric: round(
                float(candidate.get("scores", {}).get(metric, 0))
                - float(source.get("scores", {}).get(metric, 0)),
                3,
            )
            for metric in COMPLEXITY_METRICS
        }
        attempt.candidate_complexity_difficulties = {
            metric: self._complexity_label(candidate, metric)
            for metric in COMPLEXITY_METRICS
        }
        attempt.candidate_complexity_difficulty = str(
            attempt.candidate_complexity_difficulties.get("combined", "unknown")
        )
        attempt.complexity_increased = attempt.complexity_deltas.get("combined", 0) > 0
        attempt.all_complexity_metrics_increased = all(
            attempt.complexity_deltas.get(metric, 0) > 0
            for metric in (
                "semantic_reasoning", "answer_construction", "repository_navigation"
            )
        )
        target = self.config.complexity_target
        rank = {
            "unknown": -1, "easy": 0, "medium": 1, "hard": 2, "very_hard": 3,
        }
        if target == "none":
            attempt.complexity_target_met = True
        elif target == "increased":
            attempt.complexity_target_met = attempt.complexity_increased
        else:
            attempt.complexity_target_met = bool(attempt.complexity_increased) and (
                rank.get(attempt.candidate_complexity_difficulty, -1)
                >= rank[target]
            )
        if (
            target != "none"
            and self.config.require_all_metric_increases
            and attempt.complexity_target_met
        ):
            attempt.complexity_target_met = attempt.all_complexity_metrics_increased

    def _test_id(self, instance_id: str) -> tuple[str, str]:
        """(pytest node id, qa dir name) from the instance's eval.sh.

        TEST_ID looks like `click_qa/<id>/files/testcase.py::Class::method`, so
        its first path segment is the qa directory the harness stages into.
        """
        path = self.source_instances / instance_id / "eval.sh"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return "", f"{self.config.repo_key}_qa"
        m = re.search(r'^TEST_ID="([^"]*)"', text, re.MULTILINE)
        test_id = m.group(1) if m else ""
        qa_dir = test_id.split("/", 1)[0] if "/" in test_id else f"{self.config.repo_key}_qa"
        return test_id, qa_dir

    def _baseline_coverage(self, instance_id: str) -> CoverageSignature:
        """Original trace, from the instance dir or the run's logs/ tree."""
        for candidate in (
            self.source_instances / instance_id / "trace.log",
            self.config.run_dir / "logs" / instance_id / "harvest" / "trace.log",
        ):
            if candidate.is_file():
                sig = self.extractor.extract_file(candidate)
                if sig:
                    return sig
        return CoverageSignature()

    # -- repo snapshot for the proposer's read tools ---------------------------
    def repo_root(self) -> Path:
        if self._repo_root is not None:
            return self._repo_root
        snapshot = self.config.run_dir / ".llm_repo_snapshot"
        if snapshot.is_dir():
            for child in sorted(snapshot.iterdir()):
                if child.is_dir() and any(child.iterdir()):
                    self._repo_root = child
                    self._log(f"[perturb] reusing repo snapshot: {child}")
                    return child
        dest = self.output_root / ".llm_repo_snapshot" / self.config.repo_key
        if dest.is_dir() and any(dest.iterdir()):
            self._repo_root = dest
            return dest
        from ..llm_eval import build_container_runtime

        runtime = build_container_runtime(self.config.container_runtime)
        if not runtime.is_available():
            raise RuntimeError(
                f"container runtime '{self.config.container_runtime}' unavailable "
                "for the repo snapshot the proposer's read tools need"
            )
        self._log(f"[perturb] snapshotting /testbed from {self.config.image} -> {dest}")
        runtime.ensure_image_available(self.config.image, repo_name=self.config.repo_key)
        dest.mkdir(parents=True, exist_ok=True)
        runtime.copy_dir_contents(
            image=self.config.image, src_dir="/testbed", dest=dest,
            name_hint=self.config.repo_key,
        )
        self._repo_root = dest
        return dest

    # -- flip stage ------------------------------------------------------------
    def flip_checker(self) -> FlipChecker:
        if self._flip_checker is None:
            cfg = self.config
            self._flip_checker = FlipChecker(
                provider=cfg.flip_provider,
                model=cfg.flip_model,
                repo_root=self.repo_root(),
                out_root=self.output_root / "evaluation" / "llm"
                / f"{cfg.flip_provider}/{cfg.flip_model}".replace("/", "_"),
                temperature=cfg.target_temperature,
                reasoning_effort=cfg.target_effort,
                max_read_lines=cfg.target_max_read_lines,
                repo_map_mode=cfg.repo_map_mode,
                float_tol=cfg.float_tol,
            )
        return self._flip_checker

    def load_baselines(self) -> None:
        """Original pass/fail for the target model, from the source run."""
        cfg = self.config
        self._baseline_verdicts = original_verdicts(
            cfg.run_dir, cfg.flip_provider, cfg.flip_model
        )
        if self._baseline_verdicts:
            passed = sum(1 for v in self._baseline_verdicts.values() if v)
            self._log(
                f"[perturb] baseline from evaluation_report.json: "
                f"{passed}/{len(self._baseline_verdicts)} passed "
                f"({cfg.flip_provider}/{cfg.flip_model})"
            )

    def baseline_for(self, original_id: str) -> Optional[bool]:
        """Did the target model answer the ORIGINAL correctly?

        Uses the recorded verdict when available; otherwise evaluates the
        original once (and caches it), because without it a "flip" cannot be
        distinguished from an instance the model never solved anyway.
        """
        if original_id in self._baseline_verdicts:
            return self._baseline_verdicts[original_id]
        if not self.config.baseline_check:
            return None
        verdict = self.flip_checker().check(self.source_instances / original_id)
        if verdict.infra_error:
            self._note_infra(verdict, f"baseline {original_id}")
            return None
        if not verdict.usable:
            self._log(f"    baseline {original_id}: unavailable ({verdict.reason[:120]})")
            return None
        self._baseline_verdicts[original_id] = verdict.passed
        self._log(f"    baseline {original_id}: model {'PASSED' if verdict.passed else 'failed'}")
        return verdict.passed

    def _note_infra(self, verdict: FlipVerdict, where: str) -> None:
        """A provider refusal is never a verdict; stop rather than fabricate one."""
        self.infra_aborted = True
        self._log(
            f"    !! provider refused during {where}: {verdict.infra_error[:200]}\n"
            f"    !! flip results would be fabricated, so the flip stage is now OFF "
            f"for the rest of this run (instances are still perturbed and kept)."
        )

    def _run_flip(self, attempt: Attempt, instance_dir: Path) -> None:
        if not self.config.flip_check or self.infra_aborted:
            return
        original = self.baseline_for(attempt.original_id)
        if self.infra_aborted:
            return
        attempt.model_passed_original = original

        verdict = self.flip_checker().check(instance_dir)
        if verdict.infra_error:
            attempt.flip_infra_error = verdict.infra_error
            self._note_infra(verdict, f"flip check {attempt.new_id}")
            return
        if not verdict.usable:
            attempt.flip_detail = verdict.reason[:300]
            return
        attempt.model_passed_perturbed = verdict.passed
        attempt.flip_detail = verdict.reason[:300]
        attempt.flip_cost_usd = verdict.cost_usd
        if original is not None:
            attempt.flipped = bool(original) and not verdict.passed

    # -- screening -------------------------------------------------------------
    def _screen(self, instance_dir: Path, category: str) -> list[str]:
        """Failing rule names for a harvested instance ([] means it passed)."""
        ctx = InstanceContext.load(instance_dir, category, [])
        failures = []
        for rule in DEFAULT_RULES:
            try:
                result = rule.check(ctx)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{rule.name}: {exc}")
                continue
            if not result.passed:
                failures.append(f"{rule.name}: {result.reason}")
        return failures

    # -- one candidate ---------------------------------------------------------
    def evaluate_candidate(
        self,
        original_id: str,
        new_id: str,
        source: str,
        variant_index: int,
        baseline: CoverageSignature,
        feedback_iteration: Optional[int] = None,
    ) -> Attempt:
        category = self._category(original_id)
        attempt = Attempt(
            original_id=original_id, new_id=new_id, variant_index=variant_index,
            category=category, feedback_iteration=feedback_iteration,
        )

        materialized = self.materializer.materialize(original_id, new_id, source)
        if materialized is None:
            attempt.stage, attempt.detail = "materialize", "source instance missing"
            return attempt

        result = self.harvester.harvest(new_id, container_name=f"qa-pert-{abs(hash(new_id)) % 10000}")
        self.harvester.cleanup_artifacts(new_id)
        if not result.ok:
            # Execution is the validator: a broken perturbation has no oracle.
            attempt.stage, attempt.detail = "harvest", result.detail
            self.materializer.remove(new_id)
            return attempt

        new_oracle = self._oracle(new_id, base=self.output_instances)
        old_oracle = self._oracle(original_id)
        attempt.oracle_changed = (
            json.dumps(new_oracle.get("oracle_answer"), sort_keys=True, default=str)
            != json.dumps(old_oracle.get("oracle_answer"), sort_keys=True, default=str)
        )

        sig = self.extractor.extract_file(result.trace_path) if result.trace_path else None
        if sig:
            attempt.trace_line_events = sum(1 for e in sig.events if e[3] == "line")
        if baseline:
            attempt.baseline_line_events = sum(1 for e in baseline.events if e[3] == "line")
            if attempt.baseline_line_events:
                attempt.trace_ratio = round(
                    attempt.trace_line_events / attempt.baseline_line_events, 3
                )
        if sig and baseline:
            attempt.new_lines = len(sig.new_lines_vs(baseline))
            attempt.new_edges = len(sig.new_edges_vs(baseline))
            attempt.same_path_as_original = sig.same_path_as(baseline)
            attempt.trace_changed = not attempt.same_path_as_original

        self._measure_candidate_complexity(attempt, original_id, materialized.instance_dir)

        if self.config.screen:
            attempt.screening_failures = self._screen(materialized.instance_dir, category)
            if attempt.screening_failures:
                attempt.stage = "screen"
                attempt.detail = "; ".join(attempt.screening_failures)[:300]
                self.materializer.remove(new_id)
                return attempt

        if (
            self.config.complexity_target != "none"
            and not self.config.keep_below_complexity_target
            and attempt.complexity_target_met is not True
        ):
            attempt.stage = "complexity"
            source_score = attempt.source_complexity_scores.get("combined", "unknown")
            candidate_score = attempt.candidate_complexity_scores.get("combined", "unknown")
            attempt.detail = (
                f"combined complexity {source_score} -> {candidate_score}; "
                f"candidate label={attempt.candidate_complexity_difficulty or 'unknown'}, "
                f"required target={self.config.complexity_target}; "
                f"all metric dimensions increased="
                f"{attempt.all_complexity_metrics_increased}"
            )
            self.materializer.remove(new_id)
            return attempt

        # NOTE: an unchanged oracle is RECORDED, not rejected. Whether a
        # perturbation that leaves the answer identical is useless (a duplicate
        # question) or interesting (same answer, different inputs -- a model that
        # now fails it memorised rather than reasoned) depends on the analysis,
        # so the pipeline measures and lets the caller decide.

        self._run_flip(attempt, materialized.instance_dir)
        if self.config.require_flip and attempt.flipped is not True:
            attempt.stage = "flip"
            attempt.detail = (
                "did not flip the target model"
                if attempt.flip_infra_error == "" else "flip check unavailable"
            )
            self.materializer.remove(new_id)
            return attempt

        attempt.kept = True
        attempt.stage, attempt.detail = "kept", "ok"
        self.materializer.write_metadata(materialized.instance_dir, {
            "perturbed_from": original_id,
            "source_run_dir": str(self.config.run_dir),
            "variant_index": variant_index,
            "feedback_iteration": feedback_iteration,
            "proposer": {"provider": self.config.provider, "model": self.config.model},
            "oracle_changed": attempt.oracle_changed,
            "trace_changed": attempt.trace_changed,
            "new_lines_vs_baseline": attempt.new_lines,
            "new_edges_vs_baseline": attempt.new_edges,
            "source_complexity_scores": attempt.source_complexity_scores,
            "candidate_complexity_scores": attempt.candidate_complexity_scores,
            "candidate_complexity_components": attempt.candidate_complexity_components,
            "candidate_complexity_features": attempt.candidate_complexity_features,
            "complexity_deltas": attempt.complexity_deltas,
            "source_complexity_difficulties": attempt.source_complexity_difficulties,
            "candidate_complexity_difficulties": (
                attempt.candidate_complexity_difficulties
            ),
            "source_complexity_difficulty": attempt.source_complexity_difficulty,
            "candidate_complexity_difficulty": attempt.candidate_complexity_difficulty,
            "complexity_target": self.config.complexity_target,
            "complexity_target_met": attempt.complexity_target_met,
            "all_complexity_metrics_increased": attempt.all_complexity_metrics_increased,
            "kept_below_complexity_target": bool(
                self.config.keep_below_complexity_target
                and attempt.complexity_target_met is False
            ),
            "model_passed_original": attempt.model_passed_original,
            "model_passed_perturbed": attempt.model_passed_perturbed,
            "flipped": attempt.flipped,
            "target_model": f"{self.config.flip_provider}/{self.config.flip_model}"
            if self.config.flip_check else None,
        })
        if attempt.candidate_complexity_scores:
            (materialized.instance_dir / "difficulty.json").write_text(
                json.dumps({
                    "schema_version": 2,
                    "method": "intrinsic_complexity",
                    "difficulty": attempt.candidate_complexity_difficulties,
                    "scores": attempt.candidate_complexity_scores,
                    "components": attempt.candidate_complexity_components,
                    "features": attempt.candidate_complexity_features,
                    "source_difficulty": attempt.source_complexity_difficulties,
                    "source_scores": attempt.source_complexity_scores,
                    "deltas": attempt.complexity_deltas,
                    "target": self.config.complexity_target,
                    "target_met": attempt.complexity_target_met,
                    "all_metrics_increased": attempt.all_complexity_metrics_increased,
                    "thresholds_frozen_from": str(self.config.complexity_report)
                    if self.config.complexity_report else None,
                }, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        return attempt

    # -- main ------------------------------------------------------------------
    def _propose_with_agent(self, ids: list[str]) -> dict:
        """Agent sessions inside the repo container, N containers in parallel.

        Each worker owns one container for its lifetime: the agent CLI is
        installed once per container, then the worker pulls instances off a
        shared queue. Sessions must not share a container -- they copy variants
        over the staged test while verifying, so two concurrent sessions in one
        container would overwrite each other's test file.
        """
        from .agent_proposer import AgentProposer, AgentProposerConfig

        cfg = self.config
        work: "queue.Queue[str]" = queue.Queue()
        proposals: dict[str, list[str]] = {}
        for instance_id in ids:
            if cfg.reuse_staged_variants:
                staged_dir = self.output_root / "logs" / instance_id / "variants"
                staged = []
                for path in sorted(staged_dir.glob("variant_*.py")):
                    try:
                        source = path.read_text(encoding="utf-8")
                        compile(source, path.name, "exec")
                    except (OSError, SyntaxError):
                        continue
                    staged.append(source)
                    if len(staged) >= cfg.variants:
                        break
                if staged:
                    proposals[instance_id] = staged
                    self._log(
                        f"[perturb] {instance_id}: reusing {len(staged)} staged variant(s)"
                    )
                    continue
            work.put(instance_id)
        if work.empty():
            return proposals
        workers = min(max(1, int(cfg.agent_parallel or 1)), work.qsize())
        errors: list[str] = []

        def run_worker(worker_id: int) -> None:
            proposer = AgentProposer(
                AgentProposerConfig(
                    agent=cfg.agent, model=cfg.agent_model,
                    n=cfg.variants, timeout_s=cfg.agent_timeout_s,
                    enforce_structure=cfg.enforce_structure,
                ),
                trace=self._log,
            )
            container = Container(cfg.image, workdir="/testbed")
            tag = f"[perturb][w{worker_id}]"
            try:
                self._log(f"{tag} starting container from {cfg.image}")
                container.start()
                while True:
                    try:
                        instance_id = work.get_nowait()
                    except queue.Empty:
                        return
                    test_path = self.source_instances / instance_id / "files" / "testcase.py"
                    try:
                        source = test_path.read_text(encoding="utf-8")
                    except OSError:
                        with self._lock:
                            proposals[instance_id] = []
                        continue
                    trace_file, trace_funcs = self._trace_targets(instance_id)
                    test_id, qa_dir_name = self._test_id(instance_id)
                    shared = self.source_instances / "shared"
                    base_sig = self._baseline_coverage(instance_id)
                    baseline_events = sum(1 for e in base_sig.events if e[3] == "line")
                    baseline_distinct_lines = len(base_sig.lines)
                    variants = proposer.propose(
                        container=container,
                        original_source=source,
                        instance_id=instance_id,
                        instance_dir=self.source_instances / instance_id,
                        test_id=test_id,
                        qa_dir_name=qa_dir_name,
                        shared_dir=shared if shared.is_dir() else None,
                        trace_file=trace_file,
                        trace_funcs=trace_funcs,
                        question=str(self._oracle(instance_id).get("question", "")),
                        workdir="/testbed",
                        host_log_dir=self.output_root / "logs" / instance_id,
                        baseline_events=baseline_events,
                        baseline_distinct_lines=baseline_distinct_lines,
                        complexity_context=self.complexity_context(instance_id),
                    )
                    with self._lock:
                        proposals[instance_id] = variants
                        self._log(f"{tag} {instance_id}: {len(variants)} variant(s) proposed")
            except Exception as e:  # noqa: BLE001 — reported after join
                errors.append(f"worker {worker_id}: {e}")
            finally:
                container.stop()

        if workers == 1:
            run_worker(1)
        else:
            self._log(
                f"[perturb] {work.qsize()} unfinished instance(s) across "
                f"{workers} agent container(s)"
            )
            threads = [
                threading.Thread(target=run_worker, args=(i,), daemon=True)
                for i in range(1, workers + 1)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        for err in errors:
            self._log(f"[perturb] agent worker error: {err}")
        return proposals

    def run(self) -> list[Attempt]:
        self.prepare_output()
        ids = self._instance_ids()
        if not ids:
            self._log("[perturb] no source instances selected")
            return []
        who = (
            f"{self.config.agent}/{self.config.agent_model} (agent)"
            if self.config.proposer == "agent"
            else f"{self.config.provider}/{self.config.model} (llm)"
        )
        self._log(
            f"[perturb] {len(ids)} instance(s) x {self.config.variants} variant(s) "
            f"via {who} -> {self.output_root}"
        )
        if self.config.proposer == "llm":
            repo_root = self.repo_root()
        if self.config.flip_check:
            self._log(
                f"[perturb] flip stage ON, target "
                f"{self.config.flip_provider}/{self.config.flip_model}"
            )
            self.load_baselines()

        proposals: dict[str, list[str]] = {}
        proposer_cfg = ProposerConfig(
            provider=self.config.provider, model=self.config.model,
            temperature=self.config.temperature, reasoning_effort=self.config.reasoning_effort,
            n=self.config.variants, max_read_lines=self.config.max_read_lines,
            repo_map_mode=self.config.repo_map_mode,
            enforce_structure=self.config.enforce_structure,
        )

        def _propose(instance_id: str) -> tuple[str, list[str]]:
            proposer = LLMProposer(proposer_cfg)
            test_path = self.source_instances / instance_id / "files" / "testcase.py"
            try:
                source = test_path.read_text(encoding="utf-8")
            except OSError:
                return instance_id, []
            trace_file, trace_funcs = self._trace_targets(instance_id)
            budget = self._trace_budget(self._baseline_coverage(instance_id))
            variants = proposer.propose(
                original_source=source,
                test_rel_path=str(test_path.relative_to(self.source_instances)),
                trace_file=trace_file,
                trace_funcs=trace_funcs,
                question=str(self._oracle(instance_id).get("question", "")),
                repo_root=repo_root,
                instance_dir=self.source_instances / instance_id,
                trace_stats=budget,
                complexity_context=self.complexity_context(instance_id),
            )
            with self._lock:
                self._log(f"[perturb] {instance_id}: {len(variants)} variant(s) proposed")
            return instance_id, variants

        if self.config.proposer == "agent":
            proposals = self._propose_with_agent(ids)
        else:
            with cf.ThreadPoolExecutor(max_workers=max(1, self.config.threads)) as pool:
                for instance_id, variants in pool.map(_propose, ids):
                    proposals[instance_id] = variants

        # Harvest serially: each harvest runs a container and rewrites the same
        # qa tree inside it.
        for instance_id in ids:
            variants = proposals.get(instance_id) or []
            if not variants:
                continue
            baseline = self._baseline_coverage(instance_id)
            for index, source in enumerate(variants):
                new_id = self.config.new_instance_id(instance_id, index)
                attempt = self.evaluate_candidate(instance_id, new_id, source, index, baseline)
                self.attempts.append(attempt)
                self._log(f"    {self._fmt(attempt)}")
                self.write_report()

        self.write_report()
        kept = sum(1 for a in self.attempts if a.kept)
        self._log(f"[perturb] kept {kept}/{len(self.attempts)} candidate(s) -> {self.output_root}")
        return self.attempts

    @staticmethod
    def _fmt(a: Attempt) -> str:
        mark = "KEEP " if a.kept else "drop "
        bits = [f"{mark}{a.new_id}"]
        if a.kept:
            bits.append(
                f"oracle_changed={a.oracle_changed} trace_changed={a.trace_changed} "
                f"+{a.new_lines}L/+{a.new_edges}E trace x{a.trace_ratio}"
            )
            if a.candidate_complexity_scores:
                bits.append(
                    f"combined={a.source_complexity_scores.get('combined')}->"
                    f"{a.candidate_complexity_scores.get('combined')} "
                    f"({a.candidate_complexity_difficulty})"
                )
            if a.flipped is not None:
                bits.append("FLIP pass->fail" if a.flipped else "no-flip")
        else:
            extra = f" trace x{a.trace_ratio}" if a.trace_ratio else ""
            bits.append(f"[{a.stage}]{extra} {a.detail[:120]}")
        return " ".join(bits)

    def write_report(self) -> Path:
        path = self.output_root / "perturbation_report.json"
        kept = [a for a in self.attempts if a.kept]
        payload = {
            "source_run_dir": str(self.config.run_dir),
            "output_root": str(self.output_root),
            "repo": self.config.repo_key,
            "proposer": {
                "kind": self.config.proposer,
                "provider": self.config.provider,
                "model": self.config.model,
                "agent": self.config.agent,
                "agent_model": self.config.agent_model,
                "variants_per_instance": self.config.variants,
            },
            "complexity_objective": {
                "report": str(self.config.complexity_report)
                if self.config.complexity_report else None,
                "source_selection": self.config.source_selection,
                "selected_source_instances": self._selected_source_ids,
                "target": self.config.complexity_target,
                "keep_below_target": self.config.keep_below_complexity_target,
                "require_all_metric_increases": self.config.require_all_metric_increases,
                "combined_weights": {
                    "semantic_reasoning": 0.40,
                    "answer_construction": 0.35,
                    "repository_navigation": 0.25,
                },
                "uses_downstream_evaluation": bool(self.config.flip_check),
            },
            "summary": {
                "attempts": len(self.attempts),
                "kept": len(kept),
                "harvest_failures": sum(1 for a in self.attempts if a.stage == "harvest"),
                "screening_failures": sum(1 for a in self.attempts if a.stage == "screen"),
                "oracle_unchanged": sum(
                    1 for a in self.attempts if a.oracle_changed is False
                ),
                "oracle_changed": sum(1 for a in kept if a.oracle_changed),
                "trace_changed": sum(1 for a in kept if a.trace_changed),
                "complexity_checked": sum(
                    1 for a in self.attempts if a.complexity_target_met is not None
                ),
                "complexity_increased": sum(
                    1 for a in self.attempts if a.complexity_increased is True
                ),
                "complexity_target_met": sum(
                    1 for a in self.attempts if a.complexity_target_met is True
                ),
                "complexity_failures": sum(
                    1 for a in self.attempts if a.stage == "complexity"
                ),
                "median_trace_ratio_all_harvested": round(sorted(
                    [a.trace_ratio for a in self.attempts if a.trace_ratio] or [0]
                )[len([a for a in self.attempts if a.trace_ratio]) // 2], 3),
                "harvested_longer_than_original": sum(
                    1 for a in self.attempts if a.trace_ratio > 1.0
                ),
                "harvested_shorter_than_original": sum(
                    1 for a in self.attempts if 0 < a.trace_ratio < 1.0
                ),
                "flip_checked": sum(1 for a in self.attempts if a.flipped is not None),
                "flipped": sum(1 for a in self.attempts if a.flipped),
                "flip_infra_errors": sum(1 for a in self.attempts if a.flip_infra_error),
                "flip_cost_usd": round(
                    sum(a.flip_cost_usd or 0 for a in self.attempts), 4
                ),
            },
            "flip_stage": {
                "enabled": self.config.flip_check,
                "target_model": f"{self.config.flip_provider}/{self.config.flip_model}",
                "aborted_on_provider_refusal": self.infra_aborted,
            },
            "attempts": [a.to_dict() for a in self.attempts],
        }
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        self._write_frozen_complexity_report(kept)
        return path

    def _write_frozen_complexity_report(self, kept: list[Attempt]) -> Path:
        """Publish candidate labels without re-binning the small perturbed set."""
        report = self.output_root / "complexity_report.json"
        if not self._source_complexity:
            return report
        records = []
        for attempt in kept:
            source = self._source_complexity.get(attempt.original_id, {})
            records.append({
                "run_dir": str(self.output_root),
                "instance_id": attempt.new_id,
                "category": attempt.category,
                "answer_archetype": source.get("answer_archetype", ""),
                "scores": attempt.candidate_complexity_scores,
                "components": attempt.candidate_complexity_components,
                "features": attempt.candidate_complexity_features,
                "difficulty": attempt.candidate_complexity_difficulties,
                "perturbed_from": attempt.original_id,
                "source_difficulty": attempt.source_complexity_difficulties,
                "source_scores": attempt.source_complexity_scores,
                "score_deltas": attempt.complexity_deltas,
            })
        payload = {
            "schema_version": 2,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "methodology": {
                "intrinsic_inputs": [
                    "source plan.json", "harvested trace.log", "oracle.json",
                    "testcase.py", "eval.sh",
                ],
                "excluded_inputs": [
                    "evaluation_report.json", "downstream model outcomes",
                    "solver rollout effort",
                ],
                "combined_weights": {
                    "semantic_reasoning": 0.40,
                    "answer_construction": 0.35,
                    "repository_navigation": 0.25,
                },
                "binning": "thresholds frozen from the source complexity report",
            },
            "source_complexity_report": str(self.config.complexity_report)
            if self.config.complexity_report else None,
            "run_dirs": [str(self.output_root)],
            "instance_count": len(records),
            "thresholds": self._complexity_thresholds,
            "instances": records,
            "accuracy_by_scope": {},
        }
        report.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        return report
