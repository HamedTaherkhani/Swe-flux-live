#!/usr/bin/env python3
"""Parse trace log into S2_Loops oracle for ratio_resolve."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/_ratio.py"
TARGET_FUNC = "rich._ratio.ratio_resolve"
TARGET_INVOCATION = 1
LOOP_BODY_FIRST_LINE = 58

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


def _count_loop_iterations(events: list[dict[str, str | int]]) -> int:
    invocation = 0
    depth = 0
    iteration_count = 0
    active = False

    for event in events:
        event_type = str(event["event"])

        if event_type == "call":
            if depth == 0:
                invocation += 1
                depth = 1
                active = invocation == TARGET_INVOCATION
                if active:
                    iteration_count = 0
            else:
                depth += 1
            continue

        if event_type == "return":
            if depth == 1:
                if active:
                    return iteration_count
                depth = 0
                active = False
            elif depth > 1:
                depth -= 1
            continue

        if not active or depth != 1 or event_type != "line":
            continue

        if int(event["lineno"]) == LOOP_BODY_FIRST_LINE:
            iteration_count += 1

    raise SystemExit(
        f"Invocation {TARGET_INVOCATION} of {TARGET_FUNC} did not return"
    )


QUESTION = """\
During pytest run of \
rich_qa/ratio_ratio_resolve_s2_loops/files/testcase.py::TestRatioResolveLoops::test_ratio_resolve_flexible_minimums, \
consider the 1st invocation of rich._ratio.ratio_resolve in rich/_ratio.py \
(count function entries in chronological order during the test run, 1-based).

Inside that invocation, locate the for-loop whose header begins at source line \
57 (`for index, edge in flexible_edges:`). Define loop iteration k as the k-th \
time source line 58 (`if portion * edge.ratio <= edge.minimum_size:`, the first \
executable line of the loop body) executes during this invocation. Report the \
total number of such iterations (equivalently, how many times line 58 runs \
before the loop at line 57 finishes during this invocation).

Line numbers are 1-based positions in rich/_ratio.py as checked into the \
repository. For multi-line statements, count only the line where the statement \
begins (for example, a list comprehension that starts on line 38 is observed \
on line 38, not on its continuation lines). Decorator lines and the docstring \
block (lines 15-28) are never observation points.

Answer with a JSON object containing exactly one key, loop_iteration_count, \
whose value is a non-negative integer.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)

    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 80:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 80"
        )

    distinct_lines = {int(event["lineno"]) for event in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    line_counts: dict[int, int] = {}
    for event in line_events:
        lineno = int(event["lineno"])
        line_counts[lineno] = line_counts.get(lineno, 0) + 1
    if max(line_counts.values()) < 15:
        raise SystemExit("No line executed at least 15 times in trace")

    loop_iteration_count = _count_loop_iterations(events)
    if loop_iteration_count < 2:
        raise SystemExit(
            f"Loop iteration count too small for S2_Loops: {loop_iteration_count}"
        )

    oracle_answer = {"loop_iteration_count": loop_iteration_count}
    template_answer = {"loop_iteration_count": "int"}

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
