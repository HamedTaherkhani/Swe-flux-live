#!/usr/bin/env python3
"""Parse trace log into S6_InterProceduralCFG oracle for auto_repr."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/repr.py"
TARGET_FUNC = "rich.repr.auto.<locals>.do_replace.<locals>.auto_repr"
TARGET_INVOCATION = 47

TRACKED_FUNCS = frozenset(
    {
        TARGET_FUNC,
        "rich.repr.auto",
        "rich.repr.auto.<locals>.do_replace",
        "rich.repr.auto.<locals>.do_replace.<locals>.auto_rich_repr",
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
            invocation += 1
            depth = 1
            if invocation == TARGET_INVOCATION:
                path = []
            continue

        if invocation != TARGET_INVOCATION:
            continue

        if func == TARGET_FUNC:
            if event_type == "line" and func in TRACKED_FUNCS:
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
rich_qa/repr_auto_repr_s6_calls/files/testcase.py::TestAutoReprExecutedPath::test_direct_auto_repr_invocations, \
the nested function rich.repr.auto.<locals>.do_replace.<locals>.auto_repr in \
rich/repr.py (source lines 42-65) is invoked directly by calling the bound \
__repr__ method installed by the @auto decorator (the test never calls repr() \
or str() on the instances).

Identify the 47th invocation of \
rich.repr.auto.<locals>.do_replace.<locals>.auto_repr during that test run, \
counting each call to that function in chronological order starting at 1.

While that 47th invocation is on the call stack, collect every line event \
(executed source line) recorded for any of these tracked functions defined in \
rich/repr.py (listed by dotted module.qualname):

- rich.repr.auto.<locals>.do_replace.<locals>.auto_repr
- rich.repr.auto
- rich.repr.auto.<locals>.do_replace
- rich.repr.auto.<locals>.do_replace.<locals>.auto_rich_repr

Include line events in auto_repr itself and nested/transitive line events in \
the other tracked functions while the 47th auto_repr frame remains on the \
stack (for example, lines executed inside rich.repr.auto.<locals>.do_replace \
during that auto_repr still count). Do not include line events from functions \
outside this list. Repeated line events at the same line in the same function \
are all included in order; do not deduplicate. Generator resumptions outside \
these functions are ignored.

Each line number is the 1-based line number in the repository file where the \
traced statement begins (as reported by Python's trace machinery for line \
events). Decorator lines, the def line, and docstring lines are not line \
events and never appear.

Report the chronological executed path as executed_path: a JSON list of objects, \
each with exactly three keys:

- file: repository-relative path to the source file (for example rich/repr.py)
- func: dotted module.qualname of the function whose body is executing (for \
example rich.repr.auto.<locals>.do_replace)
- line: integer line number (for example 48)

Sort order is chronological execution order as observed during the test; do \
not reorder or sort alphabetically.\
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
