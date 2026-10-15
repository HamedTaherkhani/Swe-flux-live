#!/usr/bin/env python
"""Build oracle.json: per-line execution counts of Schema._run_validator."""

import argparse
import ast
import json
import re
import sys
from collections import Counter

TARGET = "marshmallow.schema.Schema._run_validator"
TARGET_PATH = "src/marshmallow/schema.py"
TEST_PATH = "marshmallow_qa/schema_run_validator_m1_cfg/files/testcase.py"
TEST_CLASS = "TestRunValidatorCFG"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def body_range():
    with open(TARGET_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Schema":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_run_validator":
                    return item.body[0].lineno, item.end_lineno
    fail("could not locate Schema._run_validator in source")


def build_question(first, last):
    return (
        f"Consider the test class `{TEST_CLASS}` in `{TEST_PATH}`. Run ALL of its test "
        f"methods (pytest ids `{TEST_PATH}::{TEST_CLASS}::test_*`, 12 methods, run in one "
        "pytest session under the repository's Python interpreter); the answer aggregates "
        "over every one of them. The target is the method "
        "`marshmallow.schema.Schema._run_validator` defined in `src/marshmallow/schema.py` "
        "(the test never calls it directly; it is reached via `Schema.load` / "
        "`Schema.validate`). An invocation is one call of that function (whatever Schema "
        "subclass instance it runs on), and counts are TOTALS summed over all invocations in "
        "all test methods. "
        "Definition of an executed line: a `line` event delivered by `sys.settrace` for a frame "
        "of this function, with the event's `f_lineno` being the line; each such event adds 1 "
        "to that line's count. So a line executed multiple times in one invocation counts "
        "multiple times; `call`, `return` and `exception` events do NOT count; for multi-line "
        "statements/expressions, count exactly where the interpreter reports line events "
        "(normally the line where the statement begins, but if CPython reports an event on a "
        "continuation line, that line is counted too). "
        f"Scope: every physical line from {first} to {last} inclusive, i.e. from the `try:` "
        "line (the first statement of the body) to the last line of the function. The `def` "
        "line and the parameter-list lines of the signature are excluded. Every line in scope "
        "must appear exactly once, including blank lines, comments, `else:` lines, type-only "
        "annotations and continuation lines; a line that never receives a line event is "
        "reported with `count` 0. "
        "Answer as JSON `{\"line_execution_counts\": [{\"count\": <int>, \"line\": <int>}, ...]}` "
        "where `line` is the absolute 1-based line number in `src/marshmallow/schema.py` and "
        "`count` is a non-negative JSON integer; sort the list by `line` ascending (one entry "
        "per line, no duplicates)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        fail(f"cannot read trace log: {exc}")
    if not raw:
        fail("trace log is empty")

    first, last = body_range()
    counts = Counter()
    calls = 0
    for ln in raw:
        m = LINE_RE.match(ln)
        if not m or m.group("func") != TARGET:
            continue
        if not m.group("file").endswith(TARGET_PATH):
            continue
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "line":
            counts[int(m.group("lineno"))] += 1
    if calls == 0 or not counts:
        fail("no events for target function in trace")
    stray = sorted(l for l in counts if not first <= l <= last)
    if stray:
        fail(f"line events outside scope: {stray}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(l, 0), "line": l} for l in range(first, last + 1)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(first, last),
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"calls={calls} line_events={sum(counts.values())} distinct={len(counts)}")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
