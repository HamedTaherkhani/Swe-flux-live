#!/usr/bin/env python3
"""Parse trace log into M6_InterProceduralCFG oracle for Measurement.get."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_FILE = "rich/measure.py"
TARGET_FUNC = "rich.measure.Measurement.get"
MODULE_NAME = "rich.measure"
CLASS_NAME = "Measurement"

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _enumerate_scope_functions(repo_root: Path) -> list[dict[str, str]]:
    measure_path = repo_root / TARGET_FILE
    if not measure_path.is_file():
        raise SystemExit(f"Target source not found: {measure_path}")

    tree = ast.parse(measure_path.read_text(encoding="utf-8"), filename=str(measure_path))
    entries: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            entries.append(
                {
                    "file": TARGET_FILE,
                    "func": f"{MODULE_NAME}.{node.name}",
                }
            )
            continue
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    entries.append(
                        {
                            "file": TARGET_FILE,
                            "func": f"{MODULE_NAME}.{CLASS_NAME}.{item.name}",
                        }
                    )

    entries.sort(key=lambda entry: (entry["func"], entry["file"]))
    if not entries:
        raise SystemExit(f"No in-scope functions found in {TARGET_FILE}")
    return entries


def _parse_trace_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
    for line in text.splitlines():
        if TARGET_FILE not in line.replace("\\", "/"):
            continue
        match = EVENT_RE.match(line)
        if not match:
            continue
        file_path = _normalize_path(match.group("file"))
        if file_path != TARGET_FILE:
            continue
        events.append(
            {
                "file": file_path,
                "func": match.group("func"),
                "event": match.group("event"),
                "lineno": int(match.group("lineno")),
            }
        )

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FILE} in {trace_log}"
        )

    target_calls = [
        event
        for event in events
        if event["func"] == TARGET_FUNC and event["event"] == "call"
    ]
    if not target_calls:
        raise SystemExit(f"No call events found for {TARGET_FUNC} in {trace_log}")

    return events


def _compute_invocation_counts(
    events: list[dict[str, str | int]],
    scope_functions: list[dict[str, str]],
) -> list[dict[str, int | str]]:
    scope_by_func = {entry["func"]: entry["file"] for entry in scope_functions}
    counts: dict[str, int] = {func: 0 for func in scope_by_func}

    for event in events:
        if event["event"] != "call":
            continue
        func = str(event["func"])
        if func in counts:
            counts[func] += 1

    return [
        {
            "file": scope_by_func[func],
            "func": func,
            "count": counts[func],
        }
        for func in sorted(counts.keys())
    ]


QUESTION = """\
During pytest run of \
rich_qa/measure_get_m6_calls/files/testcase.py::TestMeasurementGetInvocationCounts, \
aggregate runtime behavior across every test method in that class (pytest executes \
them in collection order by method name).

The primary target is rich.measure.Measurement.get in rich/measure.py (source lines \
79-122). Each test calls Measurement.get directly with programmatically built console \
options and renderable inputs.

Consider every function and method defined in rich/measure.py: all module-level \
functions and all methods of class Measurement that appear in that file's source. \
Include the @property method Measurement.span. Exclude nested functions, closures, \
comprehension frames, inherited NamedTuple methods not defined in this file, and \
dunder methods not defined in this file.

Function identity is the dotted module.qualname of the defining frame (example: \
rich.measure.Measurement.normalize).

One invocation is one Python trace call event for that function's frame during the \
combined run, whether entered from a test, transitively from Measurement.get, \
recursively, or from any other caller. Generator and coroutine resumptions do not \
emit a separate call event and do not increment the count.

Functions in scope that never execute must appear with count 0.

Counts are summed across ALL test methods in TestMeasurementGetInvocationCounts, \
not reported per method.

Report invocation_counts: a JSON list of objects, each with exactly three keys:

- file: repository-relative path to the defining source file (example: rich/measure.py)
- func: dotted module.qualname (example: rich.measure.Measurement.with_maximum)
- count: non-negative integer invocation total

Sort the list by func ascending (Unicode code-point order). If two entries shared \
the same func string, break ties by file ascending; this cannot occur within one \
module file.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args()

    scope_functions = _enumerate_scope_functions(args.repo_root)
    events = _parse_trace_events(args.trace_log)

    target_line_events = [
        event
        for event in events
        if event["func"] == TARGET_FUNC and event["event"] == "line"
    ]
    if len(target_line_events) < 50:
        raise SystemExit(
            f"Insufficient line events for target: {len(target_line_events)} < 50"
        )

    distinct_lines = {event["lineno"] for event in target_line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    call_events = [event for event in events if event["event"] == "call"]
    if len(call_events) < 15:
        raise SystemExit(f"Insufficient call events: {len(call_events)} < 15")

    traced_funcs = {event["func"] for event in call_events}
    if len(traced_funcs) < 4:
        raise SystemExit(
            f"Insufficient distinct traced functions: {len(traced_funcs)} < 4"
        )

    invocation_counts = _compute_invocation_counts(events, scope_functions)
    oracle_answer = {"invocation_counts": invocation_counts}
    template_answer = {
        "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
    }

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
