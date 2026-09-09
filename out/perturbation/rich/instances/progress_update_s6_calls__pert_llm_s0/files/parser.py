#!/usr/bin/env python3
"""Parse trace log into S6_InterProceduralCFG oracle for Progress.update."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/progress.py"
TARGET_FUNC = "rich.progress.Progress.update"
TARGET_INVOCATION = 28

TRACKED_FUNCS = (
    "rich.progress.Task._reset",
    "rich.progress.Progress.refresh",
    "rich.progress.Task.get_time",
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


def _compute_function_call_order(events: list[dict[str, str | int]]) -> list[dict[str, str]]:
    invocation = 0
    depth = 0
    order: list[dict[str, str]] = []

    for event in events:
        func = str(event["func"])
        event_type = str(event["event"])

        if func == TARGET_FUNC and event_type == "call":
            invocation += 1
            depth = 1
            if invocation == TARGET_INVOCATION:
                order = []
            continue

        if invocation != TARGET_INVOCATION:
            continue

        if func == TARGET_FUNC:
            if event_type == "call":
                depth += 1
            elif event_type == "return":
                depth -= 1
                if depth == 0:
                    break
            continue

        if depth > 0 and event_type == "call" and func in TRACKED_FUNCS:
            order.append({"file": TARGET_FILE, "func": func})

    if invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"Only {invocation} invocations of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if not order:
        raise SystemExit(
            f"No tracked call events during invocation {TARGET_INVOCATION} of {TARGET_FUNC}"
        )

    return order


QUESTION = """\
During pytest run of \
rich_qa/progress_update_s6_calls/files/testcase.py::TestProgressUpdateCallOrder::test_indirect_progress_via_reader_and_track, \
the function rich.progress.Progress.update in rich/progress.py (source lines 1417-1476) \
is reached only indirectly through Progress.wrap_file, _Reader.seek, and Progress.track \
(never by calling update directly in the test).

Identify the 28th invocation of rich.progress.Progress.update during that test run, \
counting each call to that function in chronological order starting at 1.

While that 28th invocation is on the call stack, collect every call (function entry) to any of these \
tracked functions defined in rich/progress.py (listed by dotted qualname):

- rich.progress.Task._reset
- rich.progress.Progress.refresh
- rich.progress.Task.get_time

Include nested and transitive calls made from callees (for example, calls that occur while \
rich.progress.Progress.refresh is running still count because the 28th update frame remains \
on the stack). Do not include calls to rich.progress.Progress.update itself. Repeated calls \
to the same tracked function are all included in order; do not deduplicate. Generator \
resumptions and calls to functions outside this list are ignored.

Report the chronological call order as function_call_order: a JSON list of objects, each \
with exactly two string keys:

- file: repository-relative path to the defining source file (for example \
rich/progress.py)
- func: dotted module.qualname of the callee (for example \
rich.progress.Progress.refresh)

Sort order is chronological call order as observed during execution; do not reorder or \
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

    function_call_order = _compute_function_call_order(events)
    oracle_answer = {"function_call_order": function_call_order}
    template_answer = {"function_call_order": [{"file": "str", "func": "str"}]}

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
