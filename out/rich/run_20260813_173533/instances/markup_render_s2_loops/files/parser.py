#!/usr/bin/env python3
"""Parse trace log into S2_Loops oracle for rich.markup.render."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "S2_Loops"
TARGET_FILE = "rich/markup.py"
TARGET_FUNC = "rich.markup.render"
TEST_ID = (
    "rich_qa/markup_render_s2_loops/files/testcase.py::"
    "MarkupRenderLoopsTest::test_seeded_render_loop_behavior"
)
LOOP_HEADER_LINE = 153
LOOP_BODY_FIRST_LINE = 154
TARGET_INVOCATION = 1

QUESTION = f"""\
During pytest run {TEST_ID}, consider the function {TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line 106).

Identify the for-loop whose header is on line {LOOP_HEADER_LINE} in {TARGET_FILE}:

    for position, plain_text, tag in _parse(markup):

An iteration of this loop is one execution of the loop body's first physical line, which is line {LOOP_BODY_FIRST_LINE} (`if plain_text is not None:`). Count how many iterations that loop performs during invocation {TARGET_INVOCATION} of {TARGET_FUNC}.

An invocation is one call event for {TARGET_FUNC} during the test run. Invocations are numbered chronologically starting at 1 (the first call event is invocation 1). Only the specified invocation counts toward the answer.

Count only event=line records whose func equals {TARGET_FUNC} exactly (module-qualified dotted name: package.module.function, e.g. rich.markup.render). Do not count line events from nested frames such as rich.markup.render.pop_style or from callees invoked from the loop body. The def line (106), decorator lines, docstring lines, and the for-loop header line ({LOOP_HEADER_LINE}) may execute as line events but are not the loop body's first line; only executions of line {LOOP_BODY_FIRST_LINE} increment the iteration count.

Line numbers are absolute, 1-based physical lines in {TARGET_FILE} as present in the repository. For a multi-line statement, Python reports the line event on the line where that statement begins.

Report the answer as JSON with top-level key loop_iteration_count whose value is a single int: the number of iterations defined above.\
"""

TEMPLATE_ANSWER = {"loop_iteration_count": "int"}

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


def _count_loop_iterations(trace_path: Path) -> int:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    in_target_invocation = False
    iteration_count = 0

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        _file, lineno, _func, event = parsed
        target_events += 1

        if event == "call":
            invocation += 1
            in_target_invocation = invocation == TARGET_INVOCATION
            continue

        if not in_target_invocation:
            continue

        if event in {"return", "exception"}:
            in_target_invocation = False
            continue

        if event == "line" and lineno == LOOP_BODY_FIRST_LINE:
            iteration_count += 1

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"trace log has only {invocation} invocations of {TARGET_FUNC}, "
            f"need invocation {TARGET_INVOCATION}"
        )
    if iteration_count == 0:
        raise SystemExit(
            f"no iterations recorded on line {LOOP_BODY_FIRST_LINE} "
            f"for invocation {TARGET_INVOCATION}"
        )

    return iteration_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    loop_iteration_count = _count_loop_iterations(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {"loop_iteration_count": loop_iteration_count},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
