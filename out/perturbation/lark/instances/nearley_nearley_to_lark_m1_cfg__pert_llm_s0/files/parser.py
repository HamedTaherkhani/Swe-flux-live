#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "lark/tools/nearley.py"
TARGET_FUNC = "lark.tools.nearley._nearley_to_lark"
TARGET_NAME = "_nearley_to_lark"

QUESTION = """Run the pytest class selection `lark_qa/nearley_nearley_to_lark_m1_cfg/files/testcase.py::TestNearleyConversionControlFlow`. Across ALL methods in that class whose names begin with `test_` (every pytest id of the form `lark_qa/nearley_nearley_to_lark_m1_cfg/files/testcase.py::TestNearleyConversionControlFlow::test_*`), what are the total runtime line-event counts for every physical body line of `lark.tools.nearley._nearley_to_lark`, defined at `lark/tools/nearley.py:113`? Aggregate counts over the complete class run and over every invocation from every test method; because these are totals, test execution order does not affect the answer.

Use CPython's `sys.settrace` meaning of a `line` event. An invocation is one runtime `call` event for exactly `lark.tools.nearley._nearley_to_lark`; invocations are conceptually numbered 1-based in chronological call-event order, although the requested result sums them. Count only `line` events emitted by each invocation's own frame, from its call through its return or exceptional exit. Do not count `call`, `return`, or `exception` events, and do not count events in callers, callees, comprehensions, or any other frames. Every repeated event on a line, including repetitions caused by loop iterations, recursion, separate invocations, or separate test methods, adds one to that line's total; do not deduplicate events.

The scope is every 1-based physical source line after the function's `def` line through the final line of its body, inclusive, as determined from the repository source: lines 114 through 141 of `lark/tools/nearley.py`. Include blank lines, comment-only lines, and physical continuation lines in the output, assigning `count: 0` whenever an in-scope line emits no line event. Exclude the `def` line and any decorator lines. A docstring line would be included as a body line, though this function has no docstring. For a multi-line executable statement or expression, attribute an event to the 1-based physical line on which CPython reports it; when CPython reports only the line where that statement or expression begins, continuation lines remain present with zero counts.

Return exactly one JSON object with the shape `{"line_execution_counts": [{"count": "int", "line": "int"}]}`. Each `line` is an absolute 1-based physical line number in the named repository file, and each `count` is a non-negative JSON integer total. Include exactly one object for every in-scope physical line, including lines with zero counts. Sort the list by `line` in strictly ascending order. Each list object has exactly the keys `count` and `line`; there are no tie-breakers, string conversions, omitted entries, nulls, or additional normalization."""

EVENT_RE = re.compile(
    r"\s(?P<file>\S*lark/tools/nearley\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def target_body_range(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    tree = ast.parse(source, filename=str(source_path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_NAME:
            if node.end_lineno is None:
                fail("target function has no AST end line")
            return range(node.lineno + 1, node.end_lineno + 1)
    fail(f"cannot locate {TARGET_NAME} in {source_path}")


def parse_counts(trace_text, body_lines):
    body_set = set(body_lines)
    counts = Counter()
    target_events = 0
    target_calls = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            target_calls += 1
        elif event == "line":
            line = int(match.group("line"))
            if line not in body_set:
                fail(f"target line event {line} lies outside the AST body range")
            counts[line] += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if not counts:
        fail(f"trace contains zero line events for {TARGET_FUNC}")
    return counts, target_calls


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    body_lines = list(target_body_range(Path(TARGET_FILE)))
    if not body_lines:
        fail("target function body range is empty")
    counts, target_calls = parse_counts(trace_text, body_lines)

    answer = {
        "line_execution_counts": [
            {"count": counts[line], "line": line} for line in body_lines
        ]
    }
    document = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {out_path} with {len(body_lines)} body lines "
        f"aggregated over {target_calls} target calls"
    )


if __name__ == "__main__":
    main()
