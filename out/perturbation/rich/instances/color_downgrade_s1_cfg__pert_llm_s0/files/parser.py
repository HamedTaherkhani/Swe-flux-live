#!/usr/bin/env python3
"""Parse trace log into S1_IntraProceduralCFG oracle for Color.downgrade."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/color.py"
TARGET_FUNC = "rich.color.Color.downgrade"
TARGET_INVOCATION = 18

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
        if match.group("func") != TARGET_FUNC:
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
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )

    call_events = [event for event in events if event["event"] == "call"]
    if not call_events:
        raise SystemExit(f"No call events found for {TARGET_FUNC} in {trace_log}")

    return events


def _compute_executed_path(events: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    invocation = 0
    depth = 0
    path: list[dict[str, str | int]] = []

    for event in events:
        event_type = str(event["event"])
        lineno = int(event["lineno"])

        if event_type == "call":
            if depth == 0:
                invocation += 1
                depth = 1
                if invocation == TARGET_INVOCATION:
                    path = []
            else:
                depth += 1
            continue

        if invocation != TARGET_INVOCATION or depth == 0:
            if event_type == "return" and depth == 1:
                depth = 0
            continue

        if event_type == "line":
            path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": lineno,
                }
            )
        elif event_type == "return":
            depth -= 1
            if depth == 0:
                break

    if invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"Only {invocation} invocations of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if not path:
        raise SystemExit(
            f"No executed line events during invocation {TARGET_INVOCATION} "
            f"of {TARGET_FUNC}"
        )

    return path


QUESTION = """\
During pytest run of \
rich_qa/color_downgrade_s1_cfg/files/testcase.py::TestColorDowngradeCFG::test_direct_downgrade_batch, \
the function rich.color.Color.downgrade in rich/color.py (source lines 513-568) \
is invoked directly once per generated color/target pair in the test loop.

Identify the 18th invocation of rich.color.Color.downgrade during that test run, \
counting each call event for this function in chronological order starting at 1.

For that 18th invocation only, collect every line event (event=line) recorded \
while executing inside rich.color.Color.downgrade itself. Include only line events \
whose func is exactly rich.color.Color.downgrade; do not include call or return \
events, and do not include line events from nested or transitive callees (for \
example rgb_to_hls, ColorTriplet, or Color construction). Repeated line events at \
the same line number are all included in order; do not deduplicate.

Line numbers are 1-based positions in rich/color.py as checked into the repository. \
The def line (line 513), decorator lines, and docstring lines never produce line \
events and must not appear. For statements that span multiple physical lines, \
Python's trace machinery may emit separate line events on continuation lines as well \
as on the line where the statement begins (for example, a parenthesized assignment \
may report events on both the opening line and an inner continuation line); include \
every such line event in the order it occurs.

Each executed-path element uses exactly these keys:

- file: repository-relative path string, always rich/color.py for this answer
- func: dotted module.qualname string, always rich.color.Color.downgrade for this answer
- line: integer line number (for example 514)

Report the chronological executed path as executed_path: a JSON list of objects in \
execution order; do not reorder or sort alphabetically.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)

    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 50:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 50"
        )

    distinct_lines = {event["lineno"] for event in line_events}
    if len(distinct_lines) < 12:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 12"
        )

    executed_path = _compute_executed_path(events)
    oracle_answer = {"executed_path": executed_path}
    template_answer = {
        "executed_path": [{"file": "str", "func": "str", "line": "int"}]
    }

    leaf_count = sum(
        1
        for _event in executed_path
        for _key in ("file", "func", "line")
    )
    if leaf_count < 30:
        raise SystemExit(
            f"Insufficient oracle leaf values: {leaf_count} < 30"
        )

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
