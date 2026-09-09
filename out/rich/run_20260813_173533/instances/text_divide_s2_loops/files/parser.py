#!/usr/bin/env python3
"""Parse trace log and emit oracle.json for text_divide_s2_loops."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGET_FILE = "rich/text.py"
TARGET_FUNC = "rich.text.Text.divide"
LOOP_HEADER_LINE = 1150
INVOCATION_INDEX = 1  # 1-based

_CALL_RE = re.compile(
    r"(?P<file>[^:]+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _loop_body_first_line(header_line: int, source_path: Path) -> int:
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if isinstance(node, (ast.For, ast.While)) and node.lineno == header_line:
            if not node.body:
                raise ValueError(f"Loop at line {header_line} has an empty body")
            return node.body[0].lineno
    raise ValueError(f"No loop header found at line {header_line} in {source_path}")


def _parse_trace_lines(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.is_file():
        raise SystemExit(f"Trace log not found: {trace_path}")

    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise SystemExit(f"Trace log is empty: {trace_path}")

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        match = _CALL_RE.search(line)
        if not match:
            continue
        file_path = match.group("file").replace("\\", "/")
        if TARGET_FILE not in file_path:
            continue
        func = match.group("func")
        if func != TARGET_FUNC:
            continue
        events.append(
            {
                "lineno": int(match.group("lineno")),
                "event": match.group("event"),
            }
        )

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )
    return events


def _invocations(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    invocations: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for event in events:
        kind = event["event"]
        if kind == "call":
            if current is not None:
                invocations.append(current)
            current = []
        elif current is not None:
            current.append(event)
            if kind == "return":
                invocations.append(current)
                current = None
    if current is not None:
        invocations.append(current)
    return invocations


def _count_loop_iterations(
    invocation: list[dict[str, Any]], body_first_line: int
) -> int:
    return sum(
        1
        for event in invocation
        if event["event"] == "line" and event["lineno"] == body_first_line
    )


def _build_question(body_first_line: int) -> str:
    return (
        "Category S2_Loops (loop iteration count).\n"
        "\n"
        "Test scope: pytest id "
        "`rich_qa/text_divide_s2_loops/files/testcase.py::"
        "TestTextWrapLoops::test_wrap_preserves_styled_lines` — the answer "
        "covers exactly that single test method's one execution.\n"
        "\n"
        "Target: `rich.text.Text.divide` in repo-relative file `rich/text.py`.\n"
        "\n"
        "Invocation counting: consider only `call` events whose qualified name "
        "is exactly `rich.text.Text.divide` and whose file path ends with "
        "`rich/text.py`. Number those calls in chronological order starting "
        "at 1. Invocation 1 is the earliest such call during the test run.\n"
        "\n"
        "Loop: the `while True` loop whose header is on line 1150 of "
        "`rich/text.py` (the binary-search loop that adjusts `start_line_no` "
        "from `span_start` and `line_ranges`).\n"
        "\n"
        "Iteration counting: iterations are 1-based. Iteration *n* is the *n*th "
        f"time line {body_first_line} executes during the chosen invocation — "
        "that line is the first statement in the loop body (the assignment "
        "`line_start, line_end = line_ranges[start_line_no]`). Count every "
        "`line` trace event on that line within the invocation frame; do not "
        "count the loop header line itself.\n"
        "\n"
        "Question: During invocation 1 of `rich.text.Text.divide`, how many "
        "iterations does the `while True` loop at line 1150 perform?\n"
        "\n"
        "Answer format: a JSON object with exactly one key `loop_iteration_count` "
        "whose value is a JSON number (integer) giving the iteration count."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    events = _parse_trace_lines(trace_path)
    all_invocations = _invocations(events)

    if len(all_invocations) < INVOCATION_INDEX:
        raise SystemExit(
            f"Expected at least {INVOCATION_INDEX} invocation(s) of "
            f"{TARGET_FUNC}, found {len(all_invocations)}"
        )

    source_path = _repo_root() / TARGET_FILE
    body_first_line = _loop_body_first_line(LOOP_HEADER_LINE, source_path)
    target_invocation = all_invocations[INVOCATION_INDEX - 1]
    iteration_count = _count_loop_iterations(target_invocation, body_first_line)

    if iteration_count <= 0:
        raise SystemExit(
            f"Computed non-positive loop iteration count: {iteration_count}"
        )

    oracle_answer = {"loop_iteration_count": iteration_count}
    template_answer = {"loop_iteration_count": "int"}
    question = _build_question(body_first_line)

    payload = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
