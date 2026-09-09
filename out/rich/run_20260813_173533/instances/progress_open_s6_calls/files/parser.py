#!/usr/bin/env python3
"""Parse trace log into S6_InterProceduralCFG oracle for Progress.open."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/progress.py"
TARGET_FUNC = "rich.progress.Progress.open"
TARGET_INVOCATION = 14

TRACKED_FUNCS = frozenset(
    {
        TARGET_FUNC,
        "rich.progress.Progress.add_task",
        "rich.progress.Progress.start_task",
        "rich.progress.Progress.refresh",
        "rich.progress.Progress.update",
    }
)

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


def _compute_executed_path(events: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    invocation = 0
    depth = 0
    path: list[dict[str, str | int]] = []

    for event in events:
        func = str(event["func"])
        event_type = str(event["event"])
        lineno = int(event["lineno"])

        if func == TARGET_FUNC and event_type == "call":
            if depth == 0:
                invocation += 1
                path = []
                depth = 1
            else:
                depth += 1
            continue

        if invocation != TARGET_INVOCATION:
            if func == TARGET_FUNC and event_type == "return" and depth == 1:
                depth = 0
            continue

        if func == TARGET_FUNC:
            if event_type == "line" and depth > 0 and func in TRACKED_FUNCS:
                path.append({"file": TARGET_FILE, "func": func, "line": lineno})
            if event_type == "return":
                depth -= 1
                if depth == 0:
                    break
            continue

        if depth > 0 and event_type == "line" and func in TRACKED_FUNCS:
            path.append({"file": TARGET_FILE, "func": func, "line": lineno})

    if invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"Only {invocation} invocations of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if not path:
        raise SystemExit(
            f"No executed line events during invocation {TARGET_INVOCATION} of {TARGET_FUNC}"
        )

    return path


QUESTION = """\
During pytest run of \
rich_qa/progress_open_s6_calls/files/testcase.py::TestProgressOpenCallOrder::test_indirect_open_via_module_entry, \
the function rich.progress.Progress.open in rich/progress.py (source lines 1311-1386) \
is reached through rich.progress.open (module-level entry) and through a bound method \
dispatch on an existing Progress instance (never by calling Progress.open directly as a \
literal method reference in the test).

Identify the 14th invocation of rich.progress.Progress.open during that test run, \
counting each call to that function in chronological order starting at 1.

While that 14th invocation is on the call stack, collect every line event (executed source \
line) recorded for any of these tracked functions defined in rich/progress.py (listed by \
dotted qualname):

- rich.progress.Progress.open
- rich.progress.Progress.add_task
- rich.progress.Progress.start_task
- rich.progress.Progress.refresh
- rich.progress.Progress.update

Include line events in rich.progress.Progress.open itself and nested/transitive line events \
in the other tracked functions while the 14th open frame remains on the stack (for example, \
lines executed inside rich.progress.Progress.add_task during that open still count). Do not \
include line events from functions outside this list. Repeated line events at the same line \
in the same function are all included in order; do not deduplicate. Generator resumptions \
outside these functions are ignored.

Each line number is the 1-based line number in the repository file where the traced statement \
begins (as reported by Python's trace machinery for line events). Decorator lines, the def \
line, and docstring lines are not line events and never appear.

Report the chronological executed path as executed_path: a JSON list of objects, each with \
exactly three keys:

- file: repository-relative path to the source file (for example rich/progress.py)
- func: dotted module.qualname of the function whose body is executing (for example \
rich.progress.Progress.add_task)
- line: integer line number (for example 1417)

Sort order is chronological execution order as observed during the test; do not reorder or \
sort alphabetically.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)

    target_line_events = [
        event
        for event in events
        if event["func"] == TARGET_FUNC and event["event"] == "line"
    ]
    if len(target_line_events) < 40:
        raise SystemExit(
            f"Insufficient line events for target: {len(target_line_events)} < 40"
        )

    distinct_lines = {event["lineno"] for event in target_line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    call_events = [event for event in events if event["event"] == "call"]
    if len(call_events) < 10:
        raise SystemExit(f"Insufficient call events: {len(call_events)} < 10")

    traced_funcs = {event["func"] for event in call_events}
    if len(traced_funcs) < 2:
        raise SystemExit(
            f"Insufficient distinct traced functions: {len(traced_funcs)} < 2"
        )

    executed_path = _compute_executed_path(events)
    oracle_answer = {"executed_path": executed_path}
    template_answer = {
        "executed_path": [{"file": "str", "func": "str", "line": "int"}]
    }

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
