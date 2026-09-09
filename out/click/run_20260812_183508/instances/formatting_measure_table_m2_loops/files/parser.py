from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/formatting.py"
TARGET_FUNC = "click.formatting.measure_table"

QUESTION = """Run all test methods whose names start with `test_` in the unittest class `MeasureTableNestedLoopScenarios` from `click_qa/formatting_measure_table_m2_loops/files/testcase.py` together in one pytest run, and aggregate over every invocation of `click.formatting.measure_table` in `src/click/formatting.py` made during all of those methods. Identify a covered method by the pytest id `click_qa/formatting_measure_table_m2_loops/files/testcase.py::MeasureTableNestedLoopScenarios::<method-name>`. The methods are collected in ascending lexicographic order by method name; within each method, invocations retain chronological order. An invocation is one runtime call entry into exactly the target function, numbered 1-based in that complete chronological order.

Consider the inner `for idx, col in enumerate(row):` loop whose header is at line 18, nested inside the outer `for row in rows:` loop whose header is at line 17. For each target invocation, define the inner loop's iteration count as the number of executions, in that same target frame, of the inner loop body's first statement, `widths[idx] = ...`, whose expression begins at line 19. Thus iteration N is the Nth execution of line 19 in that invocation, counted 1-based; an invocation with no execution of line 19 has count zero. Executions from separate invocations are never combined into one invocation's count. Retain every invocation, including equal counts, with no deduplication, then report the maximum and minimum of those per-invocation counts across the complete run.

Count only line 19 executions in the frame whose fully qualified function name is exactly `click.formatting.measure_table`. Do not count events in `HelpFormatter.write_dl`, `term_len`, the generator-expression frame created by the return statement, any other caller or callee, or any other function. Source line numbers are absolute, 1-based physical line numbers in the named repository file as it exists for this run. For a multi-line statement or expression, the relevant executed line is the physical line where it begins; decorator, `def`, blank, comment, and docstring lines do not count as iterations.

Return exactly one JSON object with keys `max_iterations` and `min_iterations` in that order. Each value is a JSON integer, not a quoted string; use no `repr` or `str` conversion, no null or other empty-value sentinel, no sorting of counts, and no additional fields."""


def _inner_body_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    targets = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "measure_table"
    ]
    if len(targets) != 1:
        raise RuntimeError("expected exactly one top-level measure_table function")

    loops = [
        node
        for node in ast.walk(targets[0])
        if isinstance(node, ast.For) and node.lineno == 18
    ]
    if len(loops) != 1 or not loops[0].body:
        raise RuntimeError("expected the inner for loop at line 18")
    body_line = loops[0].body[0].lineno
    if body_line != 19:
        raise RuntimeError(f"expected inner loop body at line 19, found {body_line}")
    return body_line


def _iteration_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_re = re.compile(
        r" (?P<file>\S*src/click/formatting\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    counts: list[int] = []
    active: int | None = None
    target_events = 0

    for raw_line in text.splitlines():
        match = event_re.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            if active is not None:
                raise RuntimeError("overlapping target invocations are not supported")
            counts.append(0)
            active = len(counts) - 1
        elif event == "line" and line == body_line:
            if active is None:
                raise RuntimeError("inner loop body event occurred outside an invocation")
            counts[active] += 1
        elif event == "return":
            if active is None:
                raise RuntimeError("target return event occurred outside an invocation")
            active = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not counts:
        raise RuntimeError(f"trace contains no call events for {TARGET_FUNC}")
    if active is not None:
        raise RuntimeError("trace ended before the final target invocation returned")
    return counts


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        body_line = _inner_body_line(Path.cwd() / TARGET_FILE)
        counts = _iteration_counts(args.trace_log, body_line)
        document = {
            "question_kind": "M2_Loops",
            "question": QUESTION,
            "template_answer": {
                "max_iterations": "int",
                "min_iterations": "int",
            },
            "oracle_answer": {
                "max_iterations": max(counts),
                "min_iterations": min(counts),
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(document, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: failed to build loop oracle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
