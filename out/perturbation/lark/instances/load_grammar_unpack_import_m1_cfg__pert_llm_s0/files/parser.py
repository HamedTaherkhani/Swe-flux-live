#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "lark/load_grammar.py"
TARGET_FUNC = "lark.load_grammar.GrammarBuilder._unpack_import"
TARGET_CLASS = "GrammarBuilder"
TARGET_METHOD = "_unpack_import"

QUESTION = """Run the pytest class selection `lark_qa/load_grammar_unpack_import_m1_cfg/files/testcase.py::TestGrammarImportControlFlow`. Across ALL methods in that class whose names begin with `test_` (that is, every pytest id of the form `lark_qa/load_grammar_unpack_import_m1_cfg/files/testcase.py::TestGrammarImportControlFlow::test_*`), what are the total runtime line-event counts for every physical body line of `lark.load_grammar.GrammarBuilder._unpack_import`, defined at `lark/load_grammar.py:1183`? Aggregate the counts over the complete class run and over every invocation from every test method; test order does not affect these totals.

Use CPython's `sys.settrace` meaning of a `line` event. An invocation is one runtime `call` event for exactly `lark.load_grammar.GrammarBuilder._unpack_import`; calls to other functions do not count as invocations. Count only `line` events emitted by that invocation's own frame, from its call through its return or exceptional exit. Do not count `call`, `return`, or `exception` events, and do not count events in callees, comprehensions, or other frames. Repeated events on the same line, whether within one invocation or across invocations and tests, each add one to that line's total; there is no event deduplication.

The scope is every 1-based physical source line after the function's `def` line through the final line of its body, inclusive, as determined from the repository source. Include blank lines, comment-only lines, and continuation lines in the output; report `count: 0` when such a line, or any other in-scope line, emits no line event. The `def` line and any decorator lines are excluded. A docstring would be part of the body scope, although this function has none. For a multi-line executable statement or expression, attribute its line event to the 1-based physical line where that statement or expression begins; other physical continuation lines remain in scope with zero.

Return exactly one JSON object with the shape `{"line_execution_counts": [{"count": "int", "line": "int"}]}`. `line` is the absolute 1-based physical line number in the named repository file, and `count` is a non-negative JSON integer total. Include exactly one object for every in-scope physical line, even when its count is zero. Sort the list by `line` in strictly ascending order; objects have exactly the keys `count` and `line`, with no additional formatting, normalization, or values represented as strings."""

EVENT_RE = re.compile(
    r"\s(?P<file>\S*lark/load_grammar\.py):(?P<line>\d+)\s+"
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
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == TARGET_METHOD:
                    if child.end_lineno is None:
                        fail("target function has no AST end line")
                    return range(child.lineno + 1, child.end_lineno + 1)
    fail(f"cannot locate {TARGET_CLASS}.{TARGET_METHOD} in {source_path}")


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
