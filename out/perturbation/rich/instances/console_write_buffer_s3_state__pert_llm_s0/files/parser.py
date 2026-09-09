#!/usr/bin/env python3
"""Parse trace log into S3_ProgramState oracle for Console._write_buffer."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/console.py"
TARGET_FUNC = "rich.console.Console._write_buffer"
FOR_LINE = 2108
TOTAL_ITERATIONS = 30

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_locals(raw: str) -> dict[str, str]:
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"locals is not a dict: {raw!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _parse_trace_events(trace_log: Path) -> list[dict]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    events: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if TARGET_FUNC not in line:
            continue
        match = LINE_EVENT_RE.match(line)
        if not match:
            continue
        file_path = _normalize_path(match.group("file"))
        if file_path != TARGET_FILE:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        event = {
            "lineno": int(match.group("lineno")),
            "event": match.group("event"),
            "locals": _parse_locals(match.group("locals")),
        }
        events.append(event)

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )
    return events


def _compute_value_history(events: list[dict]) -> list[dict[str, int | str]]:
    in_invocation = False
    bindings: dict[str, str] = {}
    for_line_hits = 0
    history: list[dict[str, int | str]] = []

    for event in events:
        event_type = event["event"]
        if event_type == "call":
            in_invocation = True
            bindings = {}
            for_line_hits = 0
            continue
        if event_type == "return":
            in_invocation = False
            continue
        if not in_invocation or event_type != "line":
            continue

        bindings.update(event["locals"])
        lineno = event["lineno"]

        if lineno == FOR_LINE:
            for_line_hits += 1
            if for_line_hits >= 2:
                step = for_line_hits - 1
                if step > TOTAL_ITERATIONS:
                    raise SystemExit(
                        f"Unexpected extra for-loop line event at step {step}"
                    )
                if "size" not in bindings:
                    raise SystemExit(
                        f"Missing local 'size' at for-line observation step {step}"
                    )
                history.append({"step": step, "value": bindings["size"]})

    if len(history) != TOTAL_ITERATIONS:
        raise SystemExit(
            f"Expected {TOTAL_ITERATIONS} history steps, found {len(history)}"
        )

    history.sort(key=lambda item: int(item["step"]))
    return history


QUESTION = """\
During pytest run of \
rich_qa/console_write_buffer_s3_state/files/testcase.py::TestConsoleWriteBufferState::test_update_screen_lines_batch_write, \
the function rich.console.Console._write_buffer in rich/console.py is reached \
indirectly (via Console.update_screen_lines and Console._check_buffer). \
Consider only the 1st invocation of _write_buffer during that test run \
(counting function entries in chronological order, 1-based).

Inside that invocation, when rich/console.py is compiled with WINDOWS patched \
to True (as the test does), execution enters the modern-Windows branch and runs \
the for-loop at source line 2108 that batches writes. Define loop iteration k \
(1 <= k <= 30) as the k-th time source line 2114 (the augmented assignment \
size += len(line), which both reads and writes size) finishes executing during \
that invocation.

Line numbers are 1-based positions in rich/console.py as checked into the \
repository. For multi-line statements, only the line where the statement begins \
is numbered.

The observation point for iteration k is the program state immediately before \
the (k+1)-th execution of source line 2108 begins during this invocation—\
equivalently, immediately after line 2114 has finished executing for the k-th \
time. The first execution of line 2108 (before iteration 1 begins) is not an \
observation point.

At each observation point, read the local variable size in the _write_buffer \
stack frame and report its value as a Python repr() string (for example, the \
integer 7 is reported as the two-character string '7'; containers, if any, use \
the repr of the whole container).

Report the ordered history of size across all 30 iterations: step k (integer, \
1-based, matching iteration k) paired with that repr string. Sort the list \
ascending by step. Use the value_history answer shape: a JSON object with key \
value_history whose value is a list of objects each having keys step (int) and \
value (str).\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_events = [e for e in events if e["event"] == "line"]
    if len(line_events) < 40:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 40"
        )
    distinct_lines = {e["lineno"] for e in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    value_history = _compute_value_history(events)
    oracle_answer = {"value_history": value_history}
    template_answer = {"value_history": [{"step": "int", "value": "str"}]}

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
