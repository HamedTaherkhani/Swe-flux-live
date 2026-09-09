"""Observed solver-agent effort extracted from validation trajectories.

This module is intentionally separate from :mod:`repogen.complexity`.
Trajectory effort is behavior of a particular agent/model, not an intrinsic
property of an instance. Oracle-match outcomes are joined only after the
outcome-blind effort scores have been calculated.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional


EFFORT_COMPONENTS = (
    "exploration",
    "execution",
    "deliberation",
    "friction",
    "resources",
)

OBSERVED_EFFORT_LABELS = ("easy", "medium", "hard", "very_hard")

_CODE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".go",
    ".rs", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs",
    ".kt", ".kts", ".scala", ".sh", ".sql", ".toml", ".yaml", ".yml",
}
_SEARCH_RE = re.compile(r"(?:^|[\s|;&])(rg|grep|find|fd|ls)(?:\s|$)")
_EXECUTION_RE = re.compile(r"(?:^|[\s|;&])(python(?:3)?|pytest|bash|sh)(?:\s|$)")
_TEST_RE = re.compile(r"pytest|unittest|qa_pipeline|testcase\.py|::test[_A-Za-z]")
_INSPECTION_RE = re.compile(r"(?:^|[\s|;&])(cat|sed|head|tail|awk|jq)(?:\s|$)")
_MUTATION_RE = re.compile(r"(?:^|[\s|;&])(rm|mv|cp|mkdir|touch|chmod)(?:\s|$)")
_INSTALL_RE = re.compile(r"(?:^|[\s|;&])(pip|pip3|apt|apt-get|npm|yarn|pnpm)(?:\s|$)")
_INSTRUMENT_RE = re.compile(r"instrument|sys\.settrace|trace[_-]|coverage|pdb", re.I)
_REDIRECT_PATH_RE = re.compile(
    r"(?:>>?|\btee(?:\s+-a)?\s+)[ \t]*[\"']?(/testbed/[^\s\"'|;&]+)"
)
_SHELL_WRITE_RE = re.compile(
    r"write_text|json\.dump|\bopen\s*\([^)]*,\s*['\"][wax+]|\bcp\s|\bmv\s"
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _content_blocks(event: dict) -> list[dict]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content", [])
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            _as_text(item.get("text", item.get("content", item)))
            if isinstance(item, dict) else _as_text(item)
            for item in value
        )
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return "" if value is None else str(value)


def _timestamp(value: Any) -> Optional[_dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_seconds(start: Optional[_dt.datetime], end: Optional[_dt.datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def _trajectory_identity(run_dir: Path, path: Path) -> Optional[dict]:
    try:
        parts = path.relative_to(run_dir).parts
    except ValueError:
        return None
    # validation/solver_agent/<agent>/<model>/<instance>/rollout_N/file
    if len(parts) < 7 or parts[:2] != ("validation", "solver_agent"):
        return None
    rollout_name = parts[5]
    if not rollout_name.startswith("rollout_"):
        return None
    try:
        rollout = int(rollout_name.removeprefix("rollout_"))
    except ValueError:
        return None
    return {
        "agent": parts[2],
        "model": parts[3],
        "instance_id": parts[4],
        "rollout": rollout,
    }


def _path_kind(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/validation_answers/" in normalized:
        return "answer" if normalized.rstrip("/ ").endswith("/answer.json") else "validation_workspace"
    if "/qa_instances_eval/" in normalized:
        if normalized.endswith("question.json"):
            return "question"
        if "/files/" in normalized:
            return "test_bundle"
        return "qa_bundle"
    if normalized.startswith("/testbed/"):
        relative = normalized.removeprefix("/testbed/")
        if "/" not in relative:
            return "workspace_helper"
        return "repository"
    return "external"


def _is_source(path: str) -> bool:
    return Path(path).suffix.lower() in _CODE_SUFFIXES


def _model_usage(result: dict) -> dict[str, float]:
    aggregate = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0,
    }
    usages = result.get("modelUsage", {})
    if isinstance(usages, dict) and usages:
        for usage in usages.values():
            if not isinstance(usage, dict):
                continue
            aggregate["input_tokens"] += int(usage.get("inputTokens", 0) or 0)
            aggregate["output_tokens"] += int(usage.get("outputTokens", 0) or 0)
            aggregate["cache_creation_input_tokens"] += int(
                usage.get("cacheCreationInputTokens", 0) or 0
            )
            aggregate["cache_read_input_tokens"] += int(
                usage.get("cacheReadInputTokens", 0) or 0
            )
            aggregate["cost_usd"] += float(usage.get("costUSD", 0) or 0)
        return aggregate

    usage = result.get("usage", {}) if isinstance(result.get("usage"), dict) else {}
    aggregate["input_tokens"] = int(usage.get("input_tokens", 0) or 0)
    aggregate["output_tokens"] = int(usage.get("output_tokens", 0) or 0)
    aggregate["cache_creation_input_tokens"] = int(
        usage.get("cache_creation_input_tokens", 0) or 0
    )
    aggregate["cache_read_input_tokens"] = int(usage.get("cache_read_input_tokens", 0) or 0)
    aggregate["cost_usd"] = float(result.get("total_cost_usd", 0) or 0)
    return aggregate


def extract_trajectory(run_dir: Path, path: Path) -> Optional[dict]:
    identity = _trajectory_identity(run_dir, path)
    if identity is None:
        return None
    document = _read_json(path, None)
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        return None
    events = [event for event in document["events"] if isinstance(event, dict)]

    tools: list[dict] = []
    tool_results: dict[str, dict] = {}
    assistant_messages = 0
    assistant_text_blocks = 0
    assistant_text_characters = 0
    thinking_blocks = 0
    thinking_characters = 0
    thinking_token_estimate = 0
    result: dict = {}
    first_event_time: Optional[_dt.datetime] = None
    last_event_time: Optional[_dt.datetime] = None

    for event in events:
        when = _timestamp(event.get("timestamp"))
        if when is not None:
            first_event_time = min(first_event_time, when) if first_event_time else when
            last_event_time = max(last_event_time, when) if last_event_time else when
        if event.get("type") == "assistant":
            assistant_messages += 1
        if event.get("type") == "system" and event.get("subtype") == "thinking_tokens":
            thinking_token_estimate = max(
                thinking_token_estimate, int(event.get("estimated_tokens", 0) or 0)
            )
        if event.get("type") == "result":
            result = event
        for block in _content_blocks(event):
            block_type = block.get("type")
            if block_type == "tool_use":
                tools.append({
                    "id": str(block.get("id", "")),
                    "name": str(block.get("name", "unknown")),
                    "input": block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                    "timestamp": when,
                })
            elif block_type == "tool_result":
                content = _as_text(block.get("content", ""))
                tool_results[str(block.get("tool_use_id", ""))] = {
                    "is_error": bool(block.get("is_error", False)),
                    "characters": len(content),
                    "lines": len(content.splitlines()),
                    "timestamp": when,
                }
            elif block_type == "thinking":
                thinking_blocks += 1
                thinking_characters += len(_as_text(block.get("thinking", "")))
            elif block_type == "text":
                assistant_text_blocks += 1
                assistant_text_characters += len(_as_text(block.get("text", "")))

    tool_counts = Counter(tool["name"] for tool in tools)
    read_paths: list[str] = []
    write_paths: list[str] = []
    edit_paths: list[str] = []
    bash_written_paths: list[str] = []
    bash_commands: list[str] = []
    first_tool_time = tools[0]["timestamp"] if tools else None
    first_execution_time: Optional[_dt.datetime] = None
    first_answer_time: Optional[_dt.datetime] = None
    read_characters = 0
    read_lines = 0

    for tool in tools:
        name = tool["name"].lower()
        inputs = tool["input"]
        tool_result = tool_results.get(tool["id"], {})
        if name == "read":
            file_path = str(inputs.get("file_path", inputs.get("path", "")))
            if file_path:
                read_paths.append(file_path)
            read_characters += int(tool_result.get("characters", 0) or 0)
            read_lines += int(tool_result.get("lines", 0) or 0)
        elif name == "write":
            file_path = str(inputs.get("file_path", inputs.get("path", "")))
            if file_path:
                write_paths.append(file_path)
                if _path_kind(file_path) == "answer" and first_answer_time is None:
                    first_answer_time = tool["timestamp"]
        elif name == "edit":
            file_path = str(inputs.get("file_path", inputs.get("path", "")))
            if file_path:
                edit_paths.append(file_path)
                if _path_kind(file_path) == "answer" and first_answer_time is None:
                    first_answer_time = tool["timestamp"]
        elif name == "bash":
            command = str(inputs.get("command", ""))
            bash_commands.append(command)
            redirected = _REDIRECT_PATH_RE.findall(command)
            bash_written_paths.extend(redirected)
            if (
                "/validation_answers/" in command
                and _SHELL_WRITE_RE.search(command)
                and not any(_path_kind(item) == "answer" for item in redirected)
            ):
                # Python one-liners/scripts can write the answer without a
                # shell redirection that exposes the exact path to the regex.
                bash_written_paths.append("/testbed/validation_answers/<shell-write>/answer.json")
            if (
                first_answer_time is None
                and any(_path_kind(item) == "answer" for item in bash_written_paths)
            ):
                first_answer_time = tool["timestamp"]
            if first_execution_time is None and _EXECUTION_RE.search(command):
                first_execution_time = tool["timestamp"]

    all_paths = read_paths + write_paths + edit_paths + bash_written_paths
    repo_reads = [path for path in read_paths if _path_kind(path) == "repository"]
    source_reads = [path for path in repo_reads if _is_source(path)]
    answer_writes = [
        path for path in write_paths + edit_paths + bash_written_paths
        if _path_kind(path) == "answer"
    ]
    helper_writes = [
        path for path in write_paths + edit_paths + bash_written_paths
        if _path_kind(path) in {"workspace_helper", "repository", "validation_workspace"}
        and _path_kind(path) != "answer"
    ]

    search_commands = sum(bool(_SEARCH_RE.search(command)) for command in bash_commands)
    execution_commands = sum(bool(_EXECUTION_RE.search(command)) for command in bash_commands)
    test_commands = sum(bool(_TEST_RE.search(command)) for command in bash_commands)
    inspection_commands = sum(bool(_INSPECTION_RE.search(command)) for command in bash_commands)
    mutation_commands = sum(bool(_MUTATION_RE.search(command)) for command in bash_commands)
    install_commands = sum(bool(_INSTALL_RE.search(command)) for command in bash_commands)
    instrumentation_commands = sum(bool(_INSTRUMENT_RE.search(command)) for command in bash_commands)
    instrumentation_artifacts = len(set(helper_writes))
    repeated_commands = len(bash_commands) - len(set(bash_commands))
    tool_errors = sum(bool(item.get("is_error")) for item in tool_results.values())
    tool_result_characters = sum(int(item.get("characters", 0)) for item in tool_results.values())
    tool_result_lines = sum(int(item.get("lines", 0)) for item in tool_results.values())

    usage = _model_usage(result)
    context_tokens = (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    total_tokens = context_tokens + usage["output_tokens"]
    duration_ms = int(result.get("duration_ms", 0) or 0)
    if duration_ms <= 0:
        elapsed = _elapsed_seconds(first_event_time, last_event_time)
        duration_ms = round((elapsed or 0) * 1000)
    permission_denials = result.get("permission_denials", [])
    permission_denial_count = len(permission_denials) if isinstance(permission_denials, list) else 0

    raw = {
        "exploration": round(
            len(tools)
            + 2 * len(set(repo_reads))
            + 3 * len(set(source_reads))
            + 2 * search_commands
            + read_characters / 20000,
            6,
        ),
        "execution": round(
            len(bash_commands)
            + 2 * execution_commands
            + 3 * test_commands
            + 3 * instrumentation_artifacts
            + tool_counts.get("Write", 0)
            + tool_counts.get("Edit", 0),
            6,
        ),
        "deliberation": round(
            assistant_messages
            + thinking_token_estimate / 500
            + usage["output_tokens"] / 1000,
            6,
        ),
        "friction": round(
            3 * tool_errors
            + 2 * max(0, len(answer_writes) - 1)
            + repeated_commands
            + permission_denial_count,
            6,
        ),
        "resources": round(
            duration_ms / 60000 + context_tokens / 100000,
            6,
        ),
    }

    return {
        "run_dir": str(run_dir),
        **identity,
        "trajectory": str(path),
        "trajectory_terminal": {
            "subtype": result.get("subtype", ""),
            "is_error": bool(result.get("is_error", False)),
            "terminal_reason": result.get("terminal_reason", ""),
            "stop_reason": result.get("stop_reason", ""),
            "api_error_status": result.get("api_error_status"),
        },
        "activity": {
            "tool_calls": len(tools),
            "tool_types": dict(sorted(tool_counts.items())),
            "unique_tool_types": len(tool_counts),
            "tool_results": len(tool_results),
            "tool_errors": tool_errors,
            "tool_result_characters": tool_result_characters,
            "tool_result_lines": tool_result_lines,
            "assistant_messages": assistant_messages,
            "assistant_text_blocks": assistant_text_blocks,
            "assistant_text_characters": assistant_text_characters,
            "thinking_blocks": thinking_blocks,
            "thinking_characters": thinking_characters,
            "thinking_tokens_estimate": thinking_token_estimate,
        },
        "exploration": {
            "read_calls": len(read_paths),
            "unique_paths_read": len(set(read_paths)),
            "unique_paths_touched": len(set(all_paths)),
            "unique_repository_files_read": len(set(repo_reads)),
            "unique_source_files_read": len(set(source_reads)),
            "read_result_characters": read_characters,
            "read_result_lines": read_lines,
            "question_read": any(_path_kind(path) == "question" for path in read_paths),
            "test_bundle_files_read": len({path for path in read_paths if _path_kind(path) == "test_bundle"}),
            "answer_reads": sum(_path_kind(path) == "answer" for path in read_paths),
            "search_commands": search_commands,
            "inspection_commands": inspection_commands,
        },
        "execution": {
            "bash_calls": len(bash_commands),
            "unique_bash_commands": len(set(bash_commands)),
            "repeated_bash_commands": repeated_commands,
            "execution_commands": execution_commands,
            "test_commands": test_commands,
            "instrumentation_commands": instrumentation_commands,
            "mutation_commands": mutation_commands,
            "install_commands": install_commands,
            "write_calls": tool_counts.get("Write", 0),
            "edit_calls": tool_counts.get("Edit", 0),
            "helper_or_repo_files_written": len(set(helper_writes)),
            "instrumentation_artifacts": instrumentation_artifacts,
            "answer_writes": len(answer_writes),
            "answer_revisions": max(0, len(answer_writes) - 1),
        },
        "resources": {
            "duration_ms": duration_ms,
            "duration_api_ms": int(result.get("duration_api_ms", 0) or 0),
            "num_turns": int(result.get("num_turns", assistant_messages) or assistant_messages),
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
            "cache_read_input_tokens": usage["cache_read_input_tokens"],
            "context_tokens": context_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(usage["cost_usd"], 8),
            "permission_denials": permission_denial_count,
        },
        "timing": {
            "seconds_to_first_tool": _elapsed_seconds(first_event_time, first_tool_time),
            "seconds_to_first_execution": _elapsed_seconds(first_event_time, first_execution_time),
            "seconds_to_first_answer_write": _elapsed_seconds(first_event_time, first_answer_time),
        },
        "raw_effort": raw,
    }


def _validation_outcomes(run_dir: Path, agent: str = "") -> dict[tuple[str, str, int], dict]:
    report = _read_json(run_dir / "validation_report.json", {})
    outcomes: dict[tuple[str, str, int], dict] = {}
    for run in report.get("runs", []):
        scope = str(run.get("scope", ""))
        scope_agent, separator, model = scope.partition("/")
        if not separator or (agent and scope_agent != agent):
            continue
        for verdict in run.get("verdicts", []):
            instance_id = str(verdict.get("instance_id", ""))
            for rollout in verdict.get("details", {}).get("rollouts", []):
                try:
                    rollout_index = int(rollout.get("rollout"))
                except (TypeError, ValueError):
                    continue
                outcomes[(model, instance_id, rollout_index)] = {
                    "matched_oracle": bool(rollout.get("passed", False)),
                    "validation_reason": rollout.get("reason", ""),
                    "agent_exit_code": rollout.get("agent_exit_code"),
                    "infra_error": rollout.get("infra_error", ""),
                }
    return outcomes


def _complexity_index(path: Optional[Path]) -> dict[tuple[str, str], dict]:
    if path is None or not path.is_file():
        return {}
    report = _read_json(path, {})
    index: dict[tuple[str, str], dict] = {}
    for instance in report.get("instances", []):
        run_dir = str(Path(instance.get("run_dir", "")).resolve())
        instance_id = str(instance.get("instance_id", ""))
        index[(run_dir, instance_id)] = {
            "category": instance.get("category", ""),
            "answer_archetype": instance.get("answer_archetype", ""),
            "intrinsic_scores": instance.get("scores", {}),
            "intrinsic_difficulty": instance.get("difficulty", {}),
            "downstream_evaluation": instance.get("evaluation", {}),
        }
    return index


def _rank_percentiles(records: list[dict]) -> None:
    by_model: dict[str, list[dict]] = {}
    for record in records:
        by_model.setdefault(record["model"], []).append(record)
    weights = {
        "exploration": 0.25,
        "execution": 0.25,
        "deliberation": 0.25,
        "friction": 0.10,
        "resources": 0.15,
    }
    for model_records in by_model.values():
        for component in EFFORT_COMPONENTS:
            ordered = sorted(
                enumerate(model_records), key=lambda item: item[1]["raw_effort"][component]
            )
            index = 0
            while index < len(ordered):
                end = index + 1
                value = ordered[index][1]["raw_effort"][component]
                while end < len(ordered) and ordered[end][1]["raw_effort"][component] == value:
                    end += 1
                average_rank = (index + end - 1) / 2
                percentile = 5.0 if len(ordered) == 1 else 10.0 * average_rank / (len(ordered) - 1)
                for position in range(index, end):
                    ordered[position][1].setdefault("effort_components", {})[component] = round(
                        percentile, 3
                    )
                index = end
        for record in model_records:
            record["observed_effort_score"] = round(sum(
                weights[name] * record["effort_components"][name] for name in EFFORT_COMPONENTS
            ), 3)


def _assign_effort_labels(records: list[dict]) -> dict[str, dict[str, float]]:
    by_model: dict[str, list[dict]] = {}
    for record in records:
        by_model.setdefault(record["model"], []).append(record)
    thresholds: dict[str, dict[str, float]] = {}
    for model, members in sorted(by_model.items()):
        scores = [record["observed_effort_score"] for record in members]
        easy_max, medium_max, very_hard_min = _four_level_cutoffs(scores)
        thresholds[model] = {
            "easy_quantile": 0.25,
            "medium_quantile": 0.50,
            "very_hard_quantile": 0.75,
            "easy_max_score": round(easy_max, 6),
            "medium_max_score": round(medium_max, 6),
            "very_hard_min_score": round(very_hard_min, 6),
        }
        for record in members:
            record["observed_effort_label"] = _four_level_label(
                record["observed_effort_score"], easy_max, medium_max, very_hard_min
            )
    return thresholds


def _percentile(values: list[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _four_level_cutoffs(values: list[float]) -> tuple[float, float, float]:
    """Return outcome-blind quartile cutoffs for observed agent effort."""
    return (
        float(_percentile(values, 0.25) or 0),
        float(_percentile(values, 0.50) or 0),
        float(_percentile(values, 0.75) or 0),
    )


def _four_level_label(
    score: float, easy_max: float, medium_max: float, very_hard_min: float,
) -> str:
    if score <= easy_max:
        return "easy"
    if score <= medium_max:
        return "medium"
    if score >= very_hard_min:
        return "very_hard"
    return "hard"


_SUMMARY_FIELDS = {
    "observed_effort_score": lambda record: record["observed_effort_score"],
    **{
        f"{component}_effort": (
            lambda record, component=component: record["effort_components"][component]
        )
        for component in EFFORT_COMPONENTS
    },
    "tool_calls": lambda record: record["activity"]["tool_calls"],
    "tool_errors": lambda record: record["activity"]["tool_errors"],
    "read_calls": lambda record: record["exploration"]["read_calls"],
    "unique_repository_files_read": lambda record: record["exploration"]["unique_repository_files_read"],
    "unique_source_files_read": lambda record: record["exploration"]["unique_source_files_read"],
    "read_result_characters": lambda record: record["exploration"]["read_result_characters"],
    "search_commands": lambda record: record["exploration"]["search_commands"],
    "inspection_commands": lambda record: record["exploration"]["inspection_commands"],
    "bash_calls": lambda record: record["execution"]["bash_calls"],
    "execution_commands": lambda record: record["execution"]["execution_commands"],
    "test_commands": lambda record: record["execution"]["test_commands"],
    "instrumentation_artifacts": lambda record: record["execution"]["instrumentation_artifacts"],
    "answer_writes": lambda record: record["execution"]["answer_writes"],
    "answer_revisions": lambda record: record["execution"]["answer_revisions"],
    "thinking_tokens_estimate": lambda record: record["activity"]["thinking_tokens_estimate"],
    "duration_seconds": lambda record: record["resources"]["duration_ms"] / 1000,
    "num_turns": lambda record: record["resources"]["num_turns"],
    "context_tokens": lambda record: record["resources"]["context_tokens"],
    "output_tokens": lambda record: record["resources"]["output_tokens"],
    "total_tokens": lambda record: record["resources"]["total_tokens"],
    "cost_usd": lambda record: record["resources"]["cost_usd"],
}


def _summarize(records: list[dict]) -> dict:
    matched = [record for record in records if record.get("matched_oracle") is not None]
    summary = {
        "rollouts": len(records),
        "instances": len({(record["run_dir"], record["instance_id"]) for record in records}),
        "oracle_outcomes_available": len(matched),
        "oracle_matches": sum(bool(record.get("matched_oracle")) for record in matched),
        "oracle_match_rate": (
            round(sum(bool(record.get("matched_oracle")) for record in matched) / len(matched), 6)
            if matched else None
        ),
        "trajectory_api_errors": sum(record["trajectory_terminal"]["is_error"] for record in records),
        "metrics": {},
    }
    for name, getter in _SUMMARY_FIELDS.items():
        values = [float(getter(record)) for record in records]
        summary["metrics"][name] = {
            "mean": round(statistics.fmean(values), 6) if values else None,
            "median": round(statistics.median(values), 6) if values else None,
            "p90": round(_percentile(values, 0.9), 6) if values else None,
            "total": round(sum(values), 6) if values else None,
        }
    return summary


def _group(records: list[dict], key) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        value = key(record)
        if value is None or value == "":
            continue
        groups.setdefault(str(value), []).append(record)
    return {name: _summarize(members) for name, members in sorted(groups.items())}


def _activity_totals(records: list[dict]) -> dict:
    tool_types: Counter = Counter()
    for record in records:
        tool_types.update(record["activity"]["tool_types"])
    return {
        "tool_types": dict(sorted(tool_types.items())),
        "question_read_rollouts": sum(record["exploration"]["question_read"] for record in records),
        "test_bundle_read_rollouts": sum(
            record["exploration"]["test_bundle_files_read"] > 0 for record in records
        ),
        "source_read_rollouts": sum(
            record["exploration"]["unique_source_files_read"] > 0 for record in records
        ),
        "answer_written_rollouts": sum(record["execution"]["answer_writes"] > 0 for record in records),
        "answer_revision_rollouts": sum(
            record["execution"]["answer_revisions"] > 0 for record in records
        ),
        "search_commands": sum(record["exploration"]["search_commands"] for record in records),
        "execution_commands": sum(record["execution"]["execution_commands"] for record in records),
        "test_commands": sum(record["execution"]["test_commands"] for record in records),
        "instrumentation_artifacts": sum(
            record["execution"]["instrumentation_artifacts"] for record in records
        ),
        "tool_errors": sum(record["activity"]["tool_errors"] for record in records),
        "duration_hours": round(
            sum(record["resources"]["duration_ms"] for record in records) / 3_600_000, 6
        ),
        "thinking_tokens_estimate": sum(
            record["activity"]["thinking_tokens_estimate"] for record in records
        ),
        "context_tokens": sum(record["resources"]["context_tokens"] for record in records),
        "output_tokens": sum(record["resources"]["output_tokens"] for record in records),
        "cost_usd": round(sum(record["resources"]["cost_usd"] for record in records), 6),
    }


def _instance_summaries(
    records: list[dict], thresholds: dict[str, dict[str, float]],
) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for record in records:
        key = (record["run_dir"], record["instance_id"], record["model"])
        groups.setdefault(key, []).append(record)
    output = []
    for (run_dir, instance_id, model), members in sorted(groups.items()):
        summary = _summarize(members)
        mean_score = summary["metrics"]["observed_effort_score"]["mean"]
        model_thresholds = thresholds[model]
        label = _four_level_label(
            mean_score,
            model_thresholds["easy_max_score"],
            model_thresholds["medium_max_score"],
            model_thresholds["very_hard_min_score"],
        )
        first = members[0]
        output.append({
            "run_dir": run_dir,
            "instance_id": instance_id,
            "agent": first["agent"],
            "model": model,
            "category": first.get("category", ""),
            "answer_archetype": first.get("answer_archetype", ""),
            "intrinsic_difficulty": first.get("intrinsic_difficulty", {}),
            "observed_effort_label": label,
            "summary": summary,
        })
    return output


def _downstream_outcomes(
    run_dirs: list[Path], scope: str,
) -> dict[tuple[str, str], bool]:
    outcomes: dict[tuple[str, str], bool] = {}
    if not scope:
        return outcomes
    for run_dir in run_dirs:
        report = _read_json(run_dir / "evaluation_report.json", {})
        for run in report.get("runs", []):
            if str(run.get("scope", run.get("validator", ""))) != scope:
                continue
            for verdict in run.get("verdicts", []):
                instance_id = str(verdict.get("instance_id", ""))
                if instance_id:
                    outcomes[(str(run_dir.resolve()), instance_id)] = bool(
                        verdict.get("passed", False)
                    )
    return outcomes


def _aggregate_matched_instances(
    records: list[dict], downstream: dict[tuple[str, str], bool], downstream_scope: str,
) -> tuple[list[dict], dict[str, float], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = (record["run_dir"], record["instance_id"])
        groups.setdefault(key, []).append(record)

    instances: list[dict] = []
    for (run_dir, instance_id), members in sorted(groups.items()):
        first = members[0]
        component_means = {
            component: round(statistics.fmean(
                member["effort_components"][component] for member in members
            ), 6)
            for component in EFFORT_COMPONENTS
        }
        score = round(statistics.fmean(
            member["observed_effort_score"] for member in members
        ), 6)
        downstream_value = downstream.get((str(Path(run_dir).resolve()), instance_id))
        instances.append({
            "run_dir": run_dir,
            "instance_id": instance_id,
            "validator_models": sorted({member["model"] for member in members}),
            "matched_rollouts": len(members),
            "matched_rollouts_by_model": dict(sorted(Counter(
                member["model"] for member in members
            ).items())),
            "category": first.get("category", ""),
            "answer_archetype": first.get("answer_archetype", ""),
            "intrinsic_difficulty": first.get("intrinsic_difficulty", {}),
            "average_effort_components": component_means,
            "average_observed_effort_score": score,
            "average_raw_metrics": {
                name: round(statistics.fmean(float(getter(member)) for member in members), 6)
                for name, getter in _SUMMARY_FIELDS.items()
                if name != "observed_effort_score" and not name.endswith("_effort")
            },
            "downstream_evaluation": (
                {downstream_scope: downstream_value}
                if downstream_scope and downstream_value is not None else {}
            ),
        })

    scores = [instance["average_observed_effort_score"] for instance in instances]
    easy_max, medium_max, very_hard_min = _four_level_cutoffs(scores)
    thresholds = {
        "easy_quantile": 0.25,
        "medium_quantile": 0.50,
        "very_hard_quantile": 0.75,
        "easy_max_average_score": round(easy_max, 6),
        "medium_max_average_score": round(medium_max, 6),
        "very_hard_min_average_score": round(very_hard_min, 6),
    }
    for instance in instances:
        instance["difficulty"] = _four_level_label(
            instance["average_observed_effort_score"],
            easy_max,
            medium_max,
            very_hard_min,
        )

    accuracy = []
    for label in OBSERVED_EFFORT_LABELS:
        evaluated = [
            instance for instance in instances
            if instance["difficulty"] == label
            and downstream_scope in instance["downstream_evaluation"]
        ]
        correct = sum(
            instance["downstream_evaluation"][downstream_scope] for instance in evaluated
        )
        accuracy.append({
            "difficulty": label,
            "correct": correct,
            "total": len(evaluated),
            "accuracy": round(correct / len(evaluated), 6) if evaluated else None,
            "mean_average_effort_score": round(statistics.fmean(
                instance["average_observed_effort_score"]
                for instance in instances if instance["difficulty"] == label
            ), 6) if any(instance["difficulty"] == label for instance in instances) else None,
        })
    return instances, thresholds, accuracy


def build_report(
    run_dirs: Iterable[Path], *, agent: str = "claude-code", model: str = "",
    complexity_report: Optional[Path] = None,
    matched_only: bool = False,
    aggregate_instances: bool = False,
    downstream_evaluation_scope: str = "",
) -> dict:
    normalized_dirs = [Path(path) for path in run_dirs]
    complexity = _complexity_index(complexity_report)
    all_records: list[dict] = []
    parse_failures: list[str] = []

    for run_dir in normalized_dirs:
        outcomes = _validation_outcomes(run_dir, agent)
        pattern = f"validation/solver_agent/{agent}/*/*/rollout_*/*.traj.json"
        for path in sorted(run_dir.glob(pattern)):
            record = extract_trajectory(run_dir, path)
            if record is None:
                parse_failures.append(str(path))
                continue
            if model and record["model"] != model:
                continue
            outcome = outcomes.get((record["model"], record["instance_id"], record["rollout"]))
            if outcome:
                record.update(outcome)
            else:
                record["matched_oracle"] = None
            intrinsic = complexity.get((str(run_dir.resolve()), record["instance_id"]), {})
            record.update(intrinsic)
            all_records.append(record)

    excluded_mismatched = sum(record.get("matched_oracle") is False for record in all_records)
    excluded_unknown = sum(record.get("matched_oracle") is None for record in all_records)
    records = (
        [record for record in all_records if record.get("matched_oracle") is True]
        if matched_only else all_records
    )

    _rank_percentiles(records)
    effort_thresholds = _assign_effort_labels(records)
    downstream = _downstream_outcomes(normalized_dirs, downstream_evaluation_scope)
    averaged_instances: list[dict] = []
    average_thresholds: dict[str, float] = {}
    downstream_accuracy: list[dict] = []
    if aggregate_instances:
        averaged_instances, average_thresholds, downstream_accuracy = (
            _aggregate_matched_instances(
                records, downstream, downstream_evaluation_scope
            )
        )
    by_outcome = _group(
        records,
        lambda record: (
            "matched" if record.get("matched_oracle") is True
            else "mismatched" if record.get("matched_oracle") is False
            else "unknown"
        ),
    )
    model_instance_summaries = _instance_summaries(records, effort_thresholds)
    return {
        "schema_version": 2,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "methodology": {
            "scope": "observed behavior of a specific validator agent/model; not intrinsic difficulty",
            "outcome_blind_score": True,
            "score_normalization": "component percentile ranks within model, scaled 0..10",
            "effort_labels": (
                "four levels at the 25th/50th/75th observed-effort score "
                "quantiles within model: easy, medium, hard, very_hard"
            ),
            "score_weights": {
                "exploration": 0.25,
                "execution": 0.25,
                "deliberation": 0.25,
                "friction": 0.10,
                "resources": 0.15,
            },
            "oracle_match_usage": "joined after effort scores; never included in a raw component or score",
            "rollout_filter": "matched oracle only" if matched_only else "all rollouts",
            "instance_aggregation": (
                "mean of selected normalized rollout scores across validator models"
                if aggregate_instances else "disabled"
            ),
        },
        "run_dirs": [str(path) for path in normalized_dirs],
        "agent": agent,
        "model_filter": model,
        "matched_only": matched_only,
        "aggregate_instances": aggregate_instances,
        "downstream_evaluation_scope": downstream_evaluation_scope,
        "complexity_report": str(complexity_report) if complexity_report else None,
        "rollout_count": len(records),
        "unfiltered_rollout_count": len(all_records),
        "excluded_mismatched_rollouts": excluded_mismatched if matched_only else 0,
        "excluded_unknown_outcome_rollouts": excluded_unknown if matched_only else 0,
        "parse_failures": parse_failures,
        "effort_thresholds": effort_thresholds,
        "activity_totals": _activity_totals(records),
        "summary": {
            "overall": _summarize(records),
            "by_model": _group(records, lambda record: record["model"]),
            "by_outcome": by_outcome,
            "by_observed_effort_label": _group(
                records, lambda record: record["observed_effort_label"]
            ),
            "by_model_and_outcome": _group(
                records,
                lambda record: f"{record['model']}:{'matched' if record.get('matched_oracle') is True else 'mismatched' if record.get('matched_oracle') is False else 'unknown'}",
            ),
            "by_intrinsic_combined_difficulty": _group(
                records, lambda record: record.get("intrinsic_difficulty", {}).get("combined")
            ),
            "by_model_and_intrinsic_combined_difficulty": _group(
                records,
                lambda record: (
                    f"{record['model']}:{record.get('intrinsic_difficulty', {}).get('combined')}"
                    if record.get("intrinsic_difficulty", {}).get("combined") else ""
                ),
            ),
            "by_category": _group(records, lambda record: record.get("category")),
            "by_answer_archetype": _group(
                records, lambda record: record.get("answer_archetype")
            ),
        },
        "instances": averaged_instances if aggregate_instances else model_instance_summaries,
        "instance_model_summaries": (
            model_instance_summaries if aggregate_instances else []
        ),
        "average_instance_effort_thresholds": average_thresholds,
        "downstream_accuracy_by_average_effort_difficulty": downstream_accuracy,
        "rollouts": records,
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
