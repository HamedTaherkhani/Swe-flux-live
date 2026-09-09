#!/usr/bin/env python3
"""Parse trace log into M2_Loops oracle for rich.layout.Layout._make_region_map."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "M2_Loops"
TARGET_FILE = "rich/layout.py"
TARGET_FUNC = "rich.layout.Layout._make_region_map"
TEST_CLASS = (
    "rich_qa/layout_make_region_map_m2_loops/files/testcase.py::"
    "LayoutMakeRegionMapLoopsTest"
)
LOOP_HEADER_LINE = 352
LOOP_BODY_FIRST_LINE = 353

QUESTION = f"""\
During pytest run {TEST_CLASS}, aggregate observations across all thirteen test methods in that class (every def test_... method), in pytest collection order.

Consider the function {TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line 345). The test reaches it only indirectly through callers such as Layout.render and Layout.__rich_console__ (for example via Console.print on a Layout instance); your answer must still describe runtime loop behavior inside _make_region_map itself.

Identify the while-loop whose header is on line {LOOP_HEADER_LINE} in {TARGET_FILE}:

    while stack:

An iteration of this loop is one execution of the loop body's first physical line, which is line {LOOP_BODY_FIRST_LINE} (`append_layout_region(pop())`). Count how many iterations that loop performs during each invocation of {TARGET_FUNC}.

An invocation is one call event whose func equals {TARGET_FUNC} exactly (module-qualified dotted name: package.module.Class.method, e.g. rich.layout.Layout._make_region_map). Invocations are numbered chronologically starting at 1 across the entire test run (the first call event is invocation 1). Count only event=line records whose func equals {TARGET_FUNC} exactly. Do not count line events from nested frames, callees such as layout.splitter.divide, or comprehension/generator frames. The def line (345), decorator lines, docstring lines, and the while-loop header line ({LOOP_HEADER_LINE}) may execute as line events but are not the loop body's first line; only executions of line {LOOP_BODY_FIRST_LINE} increment the iteration count.

Line numbers are absolute, 1-based physical lines in {TARGET_FILE} as present in the repository. For a multi-line statement, Python reports the line event on the line where that statement begins.

Across every invocation during the test run, report the maximum and minimum iteration counts observed for the while-loop defined above. Report the answer as JSON with top-level keys max_iterations and min_iterations, each value a single int (decimal numeral, no quotes).\
"""

TEMPLATE_ANSWER = {"max_iterations": "int", "min_iterations": "int"}

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


def _loop_iteration_bounds(trace_path: Path) -> tuple[int, int]:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    target_events = 0
    in_invocation = False
    current_iterations = 0
    per_invocation_counts: list[int] = []

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        _file, lineno, _func, event = parsed
        target_events += 1

        if event == "call":
            in_invocation = True
            current_iterations = 0
            continue

        if not in_invocation:
            continue

        if event in {"return", "exception"}:
            per_invocation_counts.append(current_iterations)
            in_invocation = False
            continue

        if event == "line" and lineno == LOOP_BODY_FIRST_LINE:
            current_iterations += 1

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not per_invocation_counts:
        raise SystemExit(f"no completed invocations of {TARGET_FUNC} in trace log")
    if any(count == 0 for count in per_invocation_counts):
        raise SystemExit(
            f"while-loop on line {LOOP_BODY_FIRST_LINE} recorded zero iterations "
            f"for at least one invocation"
        )

    return max(per_invocation_counts), min(per_invocation_counts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    max_iterations, min_iterations = _loop_iteration_bounds(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {
            "max_iterations": max_iterations,
            "min_iterations": min_iterations,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
