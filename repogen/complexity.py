"""Intrinsic instance-complexity metrics and held-out accuracy reporting.

The scores in this module deliberately do not read ``difficulty_report.json``,
``validation_report.json``, or solver rollout artifacts.  They are computed
from the generation plan, harvested execution trace, testcase, and oracle.
Evaluation outcomes are joined only after scores and difficulty bins have been
fixed.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from .screening import NON_INSTANCE_DIRS, TraceStats


METRICS = (
    "semantic_reasoning",
    "answer_construction",
    "repository_navigation",
    "combined",
)

DIFFICULTY_LABELS = ("easy", "medium", "hard", "very_hard")

_TRACE_EVENT_RE = re.compile(
    r" (?P<path>/\S+?):(?P<lineno>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b(?P<details>[^\n]*)"
)
_TRACE_FILE_RE = re.compile(r'^\s*export\s+TRACE_FILE="([^"]+)"', re.MULTILINE)
_TRACE_FUNC_RE = re.compile(r'^\s*export\s+TRACE_FUNC="([^"]+)"', re.MULTILINE)
_PY_FILE_RE = re.compile(r"(?<![\w./-])([\w./-]+\.py)(?![\w./-])")
_PROMPT_METRICS_RE = re.compile(
    r"Structural metrics of the target \(from static analysis\):\s*\n\s*(\{[^\n]+\})"
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _saturating(value: float, scale: float) -> float:
    """Map a non-negative count smoothly to 0..10 without hard cliffs."""
    value = max(0.0, float(value))
    return 10.0 * (1.0 - math.exp(-value / scale))


def _round(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 3)


def _answer_stats(value: Any) -> dict[str, int]:
    stats = {
        "leaf_count": 0,
        "dict_field_count": 0,
        "list_count": 0,
        "ordered_element_count": 0,
        "max_list_length": 0,
        "max_depth": 0,
        "string_characters": 0,
        "numeric_digits": 0,
    }

    def visit(item: Any, depth: int) -> None:
        stats["max_depth"] = max(stats["max_depth"], depth)
        if isinstance(item, dict):
            stats["dict_field_count"] += len(item)
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            stats["list_count"] += 1
            stats["ordered_element_count"] += len(item)
            stats["max_list_length"] = max(stats["max_list_length"], len(item))
            for child in item:
                visit(child, depth + 1)
        else:
            stats["leaf_count"] += 1
            if isinstance(item, str):
                stats["string_characters"] += len(item)
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                stats["numeric_digits"] += len(str(item).replace("-", ""))

    visit(value, 1)
    return stats


def _collect_named_values(value: Any, wanted_key: str) -> set[str]:
    found: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif key == wanted_key and isinstance(item, str) and item:
            found.add(item)

    visit(value)
    return found


def _trace_path(run_dir: Path, instance_dir: Path) -> Optional[Path]:
    instance_id = instance_dir.name
    candidates = (
        instance_dir / "trace.log",
        run_dir / "instances" / "qa_artifacts" / instance_id / "trace.log",
        run_dir / "logs" / instance_id / "harvest" / "trace.log",
    )
    return next((path for path in candidates if path.is_file()), None)


def _trace_features(path: Optional[Path]) -> dict[str, float]:
    empty: dict[str, float] = {
        "total_events": 0,
        "line_events": 0,
        "distinct_lines": 0,
        "call_events": 0,
        "distinct_functions": 0,
        "exception_events": 0,
        "max_line_repetition": 0,
        "distinct_line_transitions": 0,
        "transition_entropy": 0.0,
        "dynamic_branch_points": 0,
        "dynamic_branch_alternatives": 0,
        "state_change_events": 0,
        "max_call_depth": 0,
    }
    if path is None:
        return empty
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return empty

    base = TraceStats.from_log(text)
    line_sequence: list[tuple[str, int, str]] = []
    call_depth = 0
    max_call_depth = 0
    state_change_events = 0
    for match in _TRACE_EVENT_RE.finditer(text):
        event = match.group("event")
        if event == "line":
            line_sequence.append(
                (match.group("path"), int(match.group("lineno")), match.group("func"))
            )
            details = match.group("details")
            marker = " locals="
            if marker in details and details.rpartition(marker)[2].strip() != "{}":
                # The tracer emits only locals whose safe repr changed since the
                # previous event. Counting non-empty emissions measures actual
                # state-tracking burden without interpreting potentially large
                # or repository-specific values.
                state_change_events += 1
        elif event == "call":
            call_depth += 1
            max_call_depth = max(max_call_depth, call_depth)
        elif event == "return":
            call_depth = max(0, call_depth - 1)
    transitions = Counter(zip(line_sequence, line_sequence[1:]))
    successors: dict[tuple[str, int, str], set[tuple[str, int, str]]] = {}
    for source, target in transitions:
        successors.setdefault(source, set()).add(target)
    dynamic_branch_points = sum(len(targets) > 1 for targets in successors.values())
    dynamic_branch_alternatives = sum(
        max(0, len(targets) - 1) for targets in successors.values()
    )
    transition_total = sum(transitions.values())
    entropy = 0.0
    if transition_total > 1 and len(transitions) > 1:
        raw = -sum(
            (count / transition_total) * math.log2(count / transition_total)
            for count in transitions.values()
        )
        entropy = raw / math.log2(len(transitions))
    return {
        "total_events": base.total_events,
        "line_events": base.line_events,
        "distinct_lines": base.distinct_lines,
        "call_events": base.call_events,
        "distinct_functions": base.distinct_functions,
        "exception_events": base.exception_events,
        "max_line_repetition": base.max_line_repetition,
        "distinct_line_transitions": len(transitions),
        "transition_entropy": round(entropy, 6),
        "dynamic_branch_points": dynamic_branch_points,
        "dynamic_branch_alternatives": dynamic_branch_alternatives,
        "state_change_events": state_change_events,
        "max_call_depth": max_call_depth,
    }


def _test_features(testcase: Path) -> dict[str, int]:
    empty = {"source_lines": 0, "imports": 0, "calls": 0}
    try:
        text = testcase.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return empty
    return {
        "source_lines": len(text.splitlines()),
        "imports": sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)),
        "calls": sum(isinstance(node, ast.Call) for node in ast.walk(tree)),
    }


def _eval_metadata(instance_dir: Path) -> dict[str, Any]:
    eval_sh = instance_dir / "eval.sh"
    try:
        text = eval_sh.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    file_match = _TRACE_FILE_RE.search(text)
    func_match = _TRACE_FUNC_RE.search(text)
    traced_functions = []
    if func_match:
        traced_functions = [part.strip() for part in func_match.group(1).split(",") if part.strip()]
    return {
        "target_file": file_match.group(1) if file_match else "",
        "traced_functions": traced_functions,
    }


def _screen_indirection(run_dir: Path) -> dict[str, str]:
    report = _read_json(run_dir / "screening_report.json", {})
    output: dict[str, str] = {}
    for verdict in report.get("verdicts", []):
        for result in verdict.get("results", []):
            if result.get("rule") != "target_indirection":
                continue
            reason = result.get("reason", "")
            output[verdict.get("instance_id", "")] = reason.partition(":")[0]
    return output


def _plan_entries(run_dir: Path) -> dict[str, dict]:
    plan = _read_json(run_dir / "plan.json", [])
    if not isinstance(plan, list):
        plan = []
    entries = {
        entry.get("instance_id", ""): entry
        for entry in plan
        if isinstance(entry, dict) and entry.get("instance_id")
    }
    # Some historical runs merged generated instances from another run without
    # merging plan.json.  Recover their target dossiers deterministically from
    # manifest.json + the run's complete scout output (targets.json).
    manifest = _read_json(run_dir / "manifest.json", {})
    targets_doc = _read_json(run_dir / "targets.json", {})
    targets = targets_doc.get("targets", []) if isinstance(targets_doc, dict) else []
    target_index = {
        (target.get("file", ""), target.get("qualname", "")): target
        for target in targets if isinstance(target, dict)
    }
    for item in manifest.get("instances", []) if isinstance(manifest, dict) else []:
        instance_id = item.get("instance_id", "")
        if not instance_id or instance_id in entries:
            continue
        target = target_index.get(
            (item.get("target_file", ""), item.get("target_qualname", "")), {}
        )
        if not target:
            prompt = run_dir / "logs" / instance_id / "prompt.md"
            try:
                prompt_text = prompt.read_text(encoding="utf-8", errors="replace")
            except OSError:
                prompt_text = ""
            match = _PROMPT_METRICS_RE.search(prompt_text)
            metrics = {}
            if match:
                try:
                    metrics = json.loads(match.group(1))
                except json.JSONDecodeError:
                    metrics = {}
            target = {
                "file": item.get("target_file", ""),
                "qualname": item.get("target_qualname", ""),
                "metrics": metrics,
                "callers": [],
                "callers_2hop": [],
            }
        entries[instance_id] = {
            "instance_id": instance_id,
            "category": item.get("category", ""),
            "target": target,
        }
    return entries


def _infer_exercise_mode(instance_dir: Path, traced_functions: list[str]) -> str:
    testcase = instance_dir / "files" / "testcase.py"
    try:
        text = testcase.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"
    if not traced_functions:
        return "unknown"
    target = traced_functions[0].split(".")[-1]
    if re.search(r"(?<![\w])\.?" + re.escape(target) + r"\s*\(", text):
        return "direct"
    if target in text:
        return "semi-direct"
    return "indirect"


def _semantic_score(static: dict, trace: dict) -> tuple[float, dict[str, float]]:
    control_units = (
        static.get("branches", 0)
        + static.get("boolops", 0)
        + 2 * static.get("loops", 0)
        + 2 * static.get("max_loop_nesting", 0)
        + static.get("breaks_continues", 0)
    )
    state_units = (
        static.get("assigns", 0)
        + 2 * static.get("augassigns", 0)
        + 2 * static.get("comprehensions", 0)
    )
    interprocedural_units = static.get("calls", 0) + 2 * static.get("num_local_calls", 0)
    exceptional_units = (
        2 * static.get("excepts", 0)
        + static.get("raises", 0)
        + 2 * static.get("finallys", 0)
    )
    static_components = {
        "control_flow": _round(_saturating(control_units, 12)),
        "state_tracking": _round(_saturating(state_units, 15)),
        "interprocedural": _round(_saturating(interprocedural_units, 14)),
        "exception_semantics": _round(_saturating(exceptional_units, 5)),
    }
    dynamic_control = _round(
        0.55 * _saturating(trace.get("distinct_line_transitions", 0), 75)
        + 0.45 * _saturating(trace.get("dynamic_branch_alternatives", 0), 8)
    )
    dynamic_state = _round(
        _saturating(trace.get("state_change_events", 0), 800)
    )
    dynamic_interprocedural = _round(
        0.45 * _saturating(trace.get("call_events", 0), 500)
        + 0.30 * _saturating(trace.get("distinct_functions", 0), 5)
        + 0.25 * _saturating(trace.get("max_call_depth", 0), 10)
    )
    dynamic_exceptions = _round(
        _saturating(trace.get("exception_events", 0), 20)
    )
    execution_workload = _round(
        0.45 * _saturating(trace.get("line_events", 0), 3000)
        + 0.25 * _saturating(trace.get("max_line_repetition", 0), 800)
        + 0.20 * _saturating(trace.get("distinct_lines", 0), 70)
        + 0.10 * _saturating(trace.get("call_events", 0), 500)
    )
    components = {
        # Static complexity is retained as context, but actual executed work is
        # dominant so an unvisited branch cannot make an instance very hard.
        "control_flow": _round(
            0.35 * static_components["control_flow"] + 0.65 * dynamic_control
        ),
        "state_tracking": _round(
            0.30 * static_components["state_tracking"] + 0.70 * dynamic_state
        ),
        "interprocedural": _round(
            0.35 * static_components["interprocedural"]
            + 0.65 * dynamic_interprocedural
        ),
        "exception_semantics": _round(
            0.35 * static_components["exception_semantics"]
            + 0.65 * dynamic_exceptions
        ),
        "execution_workload": execution_workload,
    }
    score = (
        0.20 * components["control_flow"]
        + 0.20 * components["state_tracking"]
        + 0.15 * components["interprocedural"]
        + 0.05 * components["exception_semantics"]
        + 0.40 * components["execution_workload"]
    )
    return _round(score), components


def _answer_score(stats: dict[str, int]) -> tuple[float, dict[str, float]]:
    precision_units = stats["string_characters"] + stats["numeric_digits"]
    components = {
        "answer_volume": _round(_saturating(stats["leaf_count"], 35)),
        "ordered_output": _round(_saturating(stats["ordered_element_count"], 30)),
        "structural_depth": _round(_saturating(max(0, stats["max_depth"] - 1), 3)),
        "exact_value_precision": _round(_saturating(precision_units, 180)),
    }
    score = sum(components.values()) / len(components)
    return _round(score), components


def _navigation_score(
    *, exercise_mode: str, relevant_files: int, relevant_functions: int,
    test: dict[str, int], callers: int, executed_lines: int = 0,
) -> tuple[float, dict[str, float]]:
    # These are navigation *supports*, not costs. Explicit paths/symbols and a
    # richer public call chain give the solver more anchors for repo search.
    # Support lowers navigation difficulty. The distinct executed-code footprint
    # raises it because the solver must locate and understand more source lines.
    # Repeated hits to one line do not increase this footprint.
    entrypoint_support = {
        "direct": 1.5,
        "semi-direct": 4.0,
        "indirect": 7.0,
    }.get(exercise_mode, 4.0)
    components = {
        "entrypoint_support": entrypoint_support,
        "explicit_file_clues": _round(_saturating(max(0, relevant_files - 1), 2.5)),
        "explicit_function_clues": _round(
            _saturating(max(0, relevant_functions - 1), 6)
        ),
        "test_context": _round(
            _saturating(
                test["imports"] + test["calls"] / 8 + test["source_lines"] / 40,
                8,
            )
        ),
        "api_centrality": _round(_saturating(callers, 5)),
        "executed_code_footprint": _round(_saturating(executed_lines, 75)),
    }
    support = (
        0.35 * components["entrypoint_support"]
        + 0.20 * components["explicit_file_clues"]
        + 0.20 * components["explicit_function_clues"]
        + 0.15 * components["test_context"]
        + 0.10 * components["api_centrality"]
    )
    uncertainty = _round(10.0 - support)
    components["weighted_navigation_support"] = _round(support)
    components["navigation_uncertainty"] = uncertainty
    score = 0.70 * uncertainty + 0.30 * components["executed_code_footprint"]
    return _round(score), components


def extract_instance(
    run_dir: Path, instance_dir: Path, *, plan_entry: Optional[dict] = None,
    screen_mode: Optional[str] = None,
) -> Optional[dict]:
    oracle = _read_json(instance_dir / "oracle.json", None)
    if not isinstance(oracle, dict) or "oracle_answer" not in oracle:
        return None
    instance_id = instance_dir.name
    plan = plan_entry if plan_entry is not None else _plan_entries(run_dir).get(instance_id, {})
    target = plan.get("target", {}) if isinstance(plan.get("target", {}), dict) else {}
    static = target.get("metrics", {}) if isinstance(target.get("metrics", {}), dict) else {}
    trace = _trace_features(_trace_path(run_dir, instance_dir))
    answer = _answer_stats(oracle["oracle_answer"])
    test = _test_features(instance_dir / "files" / "testcase.py")
    eval_meta = _eval_metadata(instance_dir)

    relevant_files = _collect_named_values(oracle["oracle_answer"], "file")
    relevant_functions = _collect_named_values(oracle["oracle_answer"], "func")
    relevant_files.update(_PY_FILE_RE.findall(str(oracle.get("question", ""))))
    if eval_meta["target_file"]:
        relevant_files.add(eval_meta["target_file"])
    relevant_functions.update(eval_meta["traced_functions"])

    if screen_mode is None:
        screen_mode = _screen_indirection(run_dir).get(instance_id, "")
    exercise_mode = str(
        plan.get("exercise_mode") or screen_mode
        or _infer_exercise_mode(instance_dir, eval_meta["traced_functions"])
    )
    callers = len(target.get("callers", []) or []) + len(target.get("callers_2hop", []) or [])

    semantic, semantic_components = _semantic_score(static, trace)
    construction, construction_components = _answer_score(answer)
    navigation, navigation_components = _navigation_score(
        exercise_mode=exercise_mode,
        relevant_files=len(relevant_files),
        relevant_functions=len(relevant_functions),
        test=test,
        callers=callers,
        executed_lines=int(trace.get("distinct_lines", 0)),
    )
    combined = _round(0.40 * semantic + 0.35 * construction + 0.25 * navigation)

    return {
        "run_dir": str(run_dir),
        "instance_id": instance_id,
        "category": str(oracle.get("question_kind", plan.get("category", ""))),
        "answer_archetype": "+".join(sorted(oracle["oracle_answer"].keys()))
        if isinstance(oracle["oracle_answer"], dict) else type(oracle["oracle_answer"]).__name__,
        "features": {
            "static_target": static,
            "trace": trace,
            "answer": answer,
            "navigation": {
                "exercise_mode": exercise_mode,
                "relevant_file_count": len(relevant_files),
                "relevant_function_count": len(relevant_functions),
                "known_callers": callers,
                "distinct_executed_lines": int(trace.get("distinct_lines", 0)),
                **test,
            },
        },
        "components": {
            "semantic_reasoning": semantic_components,
            "answer_construction": construction_components,
            "repository_navigation": navigation_components,
        },
        "scores": {
            "semantic_reasoning": semantic,
            "answer_construction": construction,
            "repository_navigation": navigation,
            "combined": combined,
        },
    }


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def assign_difficulties(
    instances: list[dict], *, easy_quantile: float = 0.25,
    medium_quantile: float = 0.50, very_hard_quantile: float = 0.75,
    stratify_by: str = "answer_archetype",
    repository_navigation_stratify_by: str = "none",
) -> dict[str, dict]:
    if not 0 < easy_quantile < medium_quantile < very_hard_quantile < 1:
        raise ValueError(
            "difficulty quantiles must satisfy "
            "0 < easy < medium < very_hard < 1"
        )
    allowed_strata = {"none", "category", "answer_archetype", "category_archetype"}
    if stratify_by not in allowed_strata:
        raise ValueError(f"stratify_by must be one of {sorted(allowed_strata)}")
    if repository_navigation_stratify_by not in allowed_strata:
        raise ValueError(
            "repository_navigation_stratify_by must be one of "
            f"{sorted(allowed_strata)}"
        )

    def stratum(instance: dict, mode: str) -> str:
        if mode == "category":
            return instance["category"]
        if mode == "answer_archetype":
            return instance["answer_archetype"]
        if mode == "category_archetype":
            return f"{instance['category']}:{instance['answer_archetype']}"
        return "all"

    thresholds: dict[str, dict] = {}
    for metric in METRICS:
        metric_stratify_by = (
            repository_navigation_stratify_by
            if metric == "repository_navigation" else stratify_by
        )
        grouped: dict[str, list[dict]] = {}
        for instance in instances:
            grouped.setdefault(stratum(instance, metric_stratify_by), []).append(instance)
        thresholds[metric] = {
            "stratify_by": metric_stratify_by,
            "easy_quantile": easy_quantile,
            "medium_quantile": medium_quantile,
            "very_hard_quantile": very_hard_quantile,
            "strata": {},
        }
        for name, members in sorted(grouped.items()):
            values = [float(instance["scores"][metric]) for instance in members]
            easy_max = _quantile(values, easy_quantile)
            medium_max = _quantile(values, medium_quantile)
            very_hard_min = _quantile(values, very_hard_quantile)
            thresholds[metric]["strata"][name] = {
                "instances": len(members),
                "easy_max_score": round(easy_max, 6),
                "medium_max_score": round(medium_max, 6),
                "very_hard_min_score": round(very_hard_min, 6),
            }
            for instance in members:
                score = instance["scores"][metric]
                if len(members) == 1:
                    label = "medium"
                elif score <= easy_max:
                    label = "easy"
                elif score <= medium_max:
                    label = "medium"
                elif score >= very_hard_min:
                    label = "very_hard"
                else:
                    label = "hard"
                instance.setdefault("difficulty", {})[metric] = label
    return thresholds


def _evaluation_outcomes(run_dir: Path, selected_scope: str = "") -> dict[str, dict[str, bool]]:
    # Historical evaluation reports may contain results produced with the
    # explicit --all-instances escape hatch. Keep those raw records for audit,
    # but downstream accuracy is defined only on oracle-validated instances.
    from .validation import agent_validated_instances

    validated = agent_validated_instances(run_dir) or set()
    report = _read_json(run_dir / "evaluation_report.json", {})
    outcomes: dict[str, dict[str, bool]] = {}
    for run in report.get("runs", []):
        scope = str(run.get("scope", run.get("validator", "")))
        if selected_scope and scope != selected_scope:
            continue
        scoped = outcomes.setdefault(scope, {})
        for verdict in run.get("verdicts", []):
            instance_id = verdict.get("instance_id")
            if instance_id and instance_id in validated:
                # Later accumulated evaluation runs supersede earlier ones.
                scoped[instance_id] = bool(verdict.get("passed"))
    return outcomes


def _accuracy_rows(instances: list[dict], scope: str) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for metric in METRICS:
        metric_rows = []
        for label in DIFFICULTY_LABELS:
            relevant = [
                instance for instance in instances
                if instance["difficulty"][metric] == label
                and scope in instance.get("evaluation", {})
            ]
            correct = sum(instance["evaluation"][scope] for instance in relevant)
            total = len(relevant)
            metric_rows.append({
                "difficulty": label,
                "correct": correct,
                "total": total,
                "accuracy": round(correct / total, 6) if total else None,
            })
        rows[metric] = metric_rows
    return rows


def build_report(
    run_dirs: Iterable[Path], *, evaluation_scope: str = "",
    easy_quantile: float = 0.25, medium_quantile: float = 0.50,
    very_hard_quantile: float = 0.75,
    stratify_by: str = "answer_archetype",
    repository_navigation_stratify_by: str = "none",
) -> dict:
    normalized_dirs = [Path(path) for path in run_dirs]
    instances: list[dict] = []
    for run_dir in normalized_dirs:
        instances_root = run_dir / "instances"
        if not instances_root.is_dir():
            continue
        plan = _plan_entries(run_dir)
        indirection = _screen_indirection(run_dir)
        for instance_dir in sorted(instances_root.iterdir()):
            if not instance_dir.is_dir() or instance_dir.name in NON_INSTANCE_DIRS:
                continue
            record = extract_instance(
                run_dir, instance_dir,
                plan_entry=plan.get(instance_dir.name, {}),
                screen_mode=indirection.get(instance_dir.name, ""),
            )
            if record is not None:
                instances.append(record)

    thresholds = assign_difficulties(
        instances,
        easy_quantile=easy_quantile,
        medium_quantile=medium_quantile,
        very_hard_quantile=very_hard_quantile,
        stratify_by=stratify_by,
        repository_navigation_stratify_by=repository_navigation_stratify_by,
    ) if instances else {}

    all_scopes: set[str] = set()
    for run_dir in normalized_dirs:
        outcomes = _evaluation_outcomes(run_dir, evaluation_scope)
        by_id = {
            instance["instance_id"]: instance
            for instance in instances if instance["run_dir"] == str(run_dir)
        }
        for scope, scoped_outcomes in outcomes.items():
            all_scopes.add(scope)
            for instance_id, passed in scoped_outcomes.items():
                if instance_id in by_id:
                    by_id[instance_id].setdefault("evaluation", {})[scope] = passed

    return {
        "schema_version": 2,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "methodology": {
            "intrinsic_inputs": ["plan.json", "harvest/trace.log", "oracle.json", "testcase.py", "eval.sh"],
            "excluded_inputs": [
                "difficulty_report.json",
                "validation_report.json",
                "cascade_validation_report.json",
                "solver rollout logs",
                "evaluation_report.json (excluded from scoring and binning)",
            ],
            "evaluation_filter": (
                "accuracy includes only instances where at least one Haiku or "
                "Fable solver-agent rollout matched the oracle"
            ),
            "combined_weights": {
                "semantic_reasoning": 0.40,
                "answer_construction": 0.35,
                "repository_navigation": 0.25,
            },
            "binning": (
                f"four levels at the {easy_quantile:.0%}/{medium_quantile:.0%}/"
                f"{very_hard_quantile:.0%} score quantiles within "
                f"{stratify_by} (repository navigation: "
                f"{repository_navigation_stratify_by}): easy, medium, hard, "
                "very_hard; evaluation outcomes are joined only after bins are frozen"
            ),
        },
        "run_dirs": [str(path) for path in normalized_dirs],
        "instance_count": len(instances),
        "thresholds": thresholds,
        "instances": instances,
        "accuracy_by_scope": {
            scope: _accuracy_rows(instances, scope) for scope in sorted(all_scopes)
        },
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


def _difficulty_stratum(record: dict, metric_thresholds: dict) -> tuple[str, dict]:
    mode = metric_thresholds.get("stratify_by", "none")
    if mode == "category":
        name = record.get("category", "")
    elif mode == "answer_archetype":
        name = record.get("answer_archetype", "")
    elif mode == "category_archetype":
        name = f"{record.get('category', '')}:{record.get('answer_archetype', '')}"
    else:
        name = "all"
    return name, metric_thresholds.get("strata", {}).get(name, {})


def _is_cascade_report(document: dict) -> bool:
    return bool(
        isinstance(document, dict)
        and ("tiers" in document or "tier_results" in document)
        and document.get("method") != "intrinsic_complexity"
    )


def _validation_only_cascade(document: dict) -> dict:
    normalized = dict(document)
    normalized["schema_version"] = 2
    normalized["purpose"] = "solver_validation_only"
    normalized["affects_difficulty"] = False
    assignments = {}
    for instance_id, raw in document.get("assignments", {}).items():
        record = dict(raw) if isinstance(raw, dict) else {}
        if "validation_band" not in record and "difficulty" in record:
            record["validation_band"] = record.pop("difficulty")
        assignments[instance_id] = record
    normalized["assignments"] = assignments
    return normalized


def materialize_difficulty_reports(
    report: dict, *, source_report: Optional[Path] = None,
) -> dict[str, int]:
    """Write canonical intrinsic difficulty artifacts into every scored run.

    A legacy cascade-owned ``difficulty_report.json`` is preserved as
    ``cascade_validation_report.json`` before replacement. Solver outcomes are
    deliberately absent from the intrinsic labels and thresholds.
    """
    grouped: dict[str, list[dict]] = {}
    for record in report.get("instances", []):
        grouped.setdefault(str(record.get("run_dir", "")), []).append(record)

    written: dict[str, int] = {}
    generated_at = str(report.get("generated_at", _dt.datetime.now().isoformat(timespec="seconds")))
    for run_dir_text, records in sorted(grouped.items()):
        run_dir = Path(run_dir_text)
        instances_dir = run_dir / "instances"
        if not instances_dir.is_dir():
            continue

        difficulty_path = run_dir / "difficulty_report.json"
        previous = _read_json(difficulty_path, {})
        cascade_path = run_dir / "cascade_validation_report.json"
        cascade_document = _read_json(cascade_path, {})
        if _is_cascade_report(previous) and not cascade_document:
            cascade_document = previous
        if cascade_document:
            write_report(_validation_only_cascade(cascade_document), cascade_path)

        assignments: dict[str, dict] = {}
        distributions = {metric: Counter() for metric in METRICS}
        for record in records:
            instance_id = str(record["instance_id"])
            strata = {}
            for metric in METRICS:
                name, threshold = _difficulty_stratum(
                    record, report.get("thresholds", {}).get(metric, {})
                )
                strata[metric] = {"name": name, **threshold}
                distributions[metric][record["difficulty"][metric]] += 1
            assignment = {
                "method": "intrinsic_complexity",
                "category": record.get("category", ""),
                "answer_archetype": record.get("answer_archetype", ""),
                "difficulty": record.get("difficulty", {}),
                "scores": record.get("scores", {}),
                "components": record.get("components", {}),
                "strata": strata,
            }
            assignments[instance_id] = assignment
            instance_path = instances_dir / instance_id / "difficulty.json"
            if instance_path.parent.is_dir():
                write_report(
                    {
                        "schema_version": 2,
                        "generated_at": generated_at,
                        **assignment,
                        "excluded_inputs": [
                            "difficulty_report.json",
                            "validation_report.json",
                            "cascade_validation_report.json",
                            "solver rollout logs",
                            "evaluation_report.json",
                        ],
                    },
                    instance_path,
                )

        # Do not leave legacy agent-derived labels on a present but unscored
        # instance (for example, one with a malformed/missing oracle).
        scored = set(assignments)
        for instance_dir in instances_dir.iterdir():
            if not instance_dir.is_dir() or instance_dir.name in NON_INSTANCE_DIRS:
                continue
            if instance_dir.name not in scored:
                stale_path = instance_dir / "difficulty.json"
                stale = _read_json(stale_path, {})
                if stale_path.is_file() and stale.get("method") != "intrinsic_complexity":
                    stale_path.unlink()

        document = {
            "schema_version": 2,
            "method": "intrinsic_complexity",
            "generated_at": generated_at,
            "run_dir": str(run_dir),
            "source_complexity_report": str(source_report) if source_report else None,
            "methodology": report.get("methodology", {}),
            "thresholds": report.get("thresholds", {}),
            "distribution": {
                metric: dict(sorted(counts.items()))
                for metric, counts in distributions.items()
            },
            "assignments": assignments,
            "validation_artifacts": {
                "solver_validation": "validation_report.json",
                "cascade_validation": (
                    "cascade_validation_report.json" if cascade_path.is_file() else None
                ),
            },
        }
        write_report(document, difficulty_path)
        written[str(run_dir)] = len(assignments)
    return written


def refresh_intrinsic_difficulties(
    run_dirs: Iterable[Path], *, aggregate_report_path: Path,
    evaluation_scope: str = "",
) -> dict:
    """Recompute pooled intrinsic labels and distribute them into each run."""
    report = build_report(run_dirs, evaluation_scope=evaluation_scope)
    write_report(report, aggregate_report_path)
    materialize_difficulty_reports(report, source_report=aggregate_report_path)
    return report
