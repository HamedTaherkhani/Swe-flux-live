#!/usr/bin/env python3
"""Parse trace log into M2_Loops oracle for Columns.__rich_console__.iter_renderables."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "M2_Loops"
TARGET_FILE = "rich/columns.py"
TARGET_FUNC = "rich.columns.Columns.__rich_console__.<locals>.iter_renderables"
TEST_CLASS = (
    "rich_qa/columns_iter_renderables_m2_loops/files/testcase.py::"
    "ColumnsIterRenderablesLoopsTest"
)
LOOP_HEADER_LINE = 100
LOOP_BODY_FIRST_LINE = 101

QUESTION = f"""\
During pytest run {TEST_CLASS}, aggregate observations across all twelve test methods in that class (every def test_... method), in pytest collection order.

Consider the nested function {TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line 86). Each test method directly exercises this function by constructing a Columns instance with column_first=True and calling Columns.__rich_console__(console, options), then fully exhausting the returned generator; each exhaustion executes iter_renderables one or more times inside __rich_console__.

Identify the for-loop whose header is on line {LOOP_HEADER_LINE} in {TARGET_FILE}:

    for index in range(item_count):

This loop runs only on the column_first branch (when self.column_first is true). An iteration of this loop is one execution of the loop body's first physical line, which is line {LOOP_BODY_FIRST_LINE} (`cells[row][col] = index`).

Count only event=line records whose func equals {TARGET_FUNC} exactly (module-qualified dotted name including <locals>, e.g. rich.columns.Columns.__rich_console__.<locals>.iter_renderables) and whose line number equals {LOOP_BODY_FIRST_LINE}. Do not count line events from nested frames, callees, or comprehension/generator frames outside iter_renderables. The def line (86), decorator lines, docstring lines, and the for-loop header line ({LOOP_HEADER_LINE}) may execute as line events but are not the loop body's first line.

Line numbers are absolute, 1-based physical lines in {TARGET_FILE} as present in the repository. For a multi-line statement, Python reports the line event on the line where that statement begins.

Because iter_renderables is a generator, resuming after a yield produces additional call/return events on yield lines (111 and 117); those frames are still the same func name. Ignore invocation boundaries entirely for this question: sum every qualifying line-{LOOP_BODY_FIRST_LINE} event across the entire pytest run, including across generator resumes and across all twelve test methods.

Report the answer as JSON with top-level key total_iterations whose value is a single int (decimal numeral, no quotes): the total count defined above.\
"""

TEMPLATE_ANSWER = {"total_iterations": "int"}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _split_trace_line(line: str) -> tuple[str, int, str, str] | None:
    match = TRACE_LINE_RE.match(line.strip())
    if not match:
        return None
    file_path = _normalize_file(match.group("file"))
    if file_path != TARGET_FILE:
        return None
    func = match.group("func")
    if func != TARGET_FUNC:
        return None
    return file_path, int(match.group("line")), func, match.group("event")


def _total_loop_iterations(trace_path: Path) -> int:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    target_events = 0
    total_iterations = 0

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        _file, lineno, _func, event = parsed
        target_events += 1
        if event == "line" and lineno == LOOP_BODY_FIRST_LINE:
            total_iterations += 1

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if total_iterations == 0:
        raise SystemExit(
            f"no iterations recorded on line {LOOP_BODY_FIRST_LINE} in trace log"
        )

    return total_iterations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    total_iterations = _total_loop_iterations(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {"total_iterations": total_iterations},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
