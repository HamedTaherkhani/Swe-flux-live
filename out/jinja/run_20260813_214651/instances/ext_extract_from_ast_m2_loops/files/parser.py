#!/usr/bin/env python3
"""Parse trace logs for extract_from_ast inner-loop iteration bounds."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/ext.py"
TARGET_FUNC = "jinja2.ext.extract_from_ast"
LOOP_HEADER_LINE = 685
LOOP_BODY_LINE = 686

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def harvest_iteration_bounds(trace_log: Path) -> tuple[int, int, list[int]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    target_events = 0
    in_invocation = False
    current_iterations = 0
    per_invocation: list[int] = []

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]

        if event == "call":
            in_invocation = True
            current_iterations = 0
        elif event == "line" and in_invocation:
            if int(parsed["lineno"]) == LOOP_BODY_LINE:
                current_iterations += 1
        elif event == "return" and in_invocation:
            per_invocation.append(current_iterations)
            in_invocation = False
            current_iterations = 0

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if not per_invocation:
        raise SystemExit(
            f"Trace contains {target_events} target events but zero completed "
            f"invocations of {TARGET_FUNC}"
        )

    return max(per_invocation), min(per_invocation), per_invocation


def build_question() -> str:
    return (
        "Consider every test method in "
        "`jinja_qa/ext_extract_from_ast_m2_loops/files/testcase.py::"
        "TestExtractFromAstLoopDynamics`. The answer aggregates behavior "
        "across **all** `test_*` methods in that class, in the chronological "
        "order pytest collects and runs them (definition order in the file).\n\n"
        "Those tests reach `jinja2.ext.extract_from_ast` in "
        f"`{TARGET_FILE}` only **indirectly**: through `jinja2.ext.babel_extract` "
        "or `InternationalizationExtension._extract` on an i18n-enabled "
        "`Environment` — never by importing or calling `extract_from_ast` "
        "directly.\n\n"
        "Target function: `jinja2.ext.extract_from_ast` (the function whose "
        f"`def` begins at line 635 of `{TARGET_FILE}`).\n\n"
        "Target loop: the `for arg in node.args:` header on line "
        f"{LOOP_HEADER_LINE} of `{TARGET_FILE}`. An **iteration** of this loop "
        f"is one execution of the loop body's first physical line (line "
        f"{LOOP_BODY_LINE}: `if isinstance(arg, nodes.Const) and isinstance("
        "arg.value, str):`). Count iterations using `sys.settrace` `line` "
        "events whose file path ends with "
        f"`{TARGET_FILE}`, whose qualified name is exactly `{TARGET_FUNC}`, "
        f"and whose line number equals {LOOP_BODY_LINE}.\n\n"
        "**Invocation** means one `call` trace event for "
        f"`{TARGET_FUNC}` during the test run, in chronological order. Because "
        "`extract_from_ast` is a "
        "generator, each time the consumer resumes it after a `yield`, Python "
        "emits another `call` event for the same logical extraction pass; treat "
        "each such `call` as a separate invocation. The matching invocation ends "
        "at the next `return` event for the same qualified name (including "
        "generator `return` events that deliver a yielded value). "
        "`exception` events are out of scope for this question.\n\n"
        "For each invocation, count how many iterations the line "
        f"{LOOP_HEADER_LINE} loop performed (line {LOOP_BODY_LINE} executions "
        "while that invocation is active). Let **max_iterations** be the "
        "maximum of those per-invocation counts across all invocations in the "
        "run, and **min_iterations** the minimum. Ties need no special handling "
        "beyond choosing the numeric max/min.\n\n"
        "Return JSON with exactly these top-level keys: `max_iterations` "
        "(integer) and `min_iterations` (integer)."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    max_iterations, min_iterations, _ = harvest_iteration_bounds(args.trace_log)

    oracle_answer = {
        "max_iterations": max_iterations,
        "min_iterations": min_iterations,
    }
    template_answer = {
        "max_iterations": "int",
        "min_iterations": "int",
    }

    payload = {
        "question_kind": "M2_Loops",
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
