#!/usr/bin/env python
"""Per-line execution counts of werkzeug ContentRange.from_header from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/datastructures/range.py"
CLASS_NAME = "ContentRange"
FUNC_NAME = "from_header"
QUALNAME = "werkzeug.datastructures.range.ContentRange.from_header"
TEST_FILE = "werkzeug_qa/range_from_header_m1_cfg_2/files/testcase.py"
TEST_CLASS = "ContentRangeParseTest"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_target(root):
    path = os.path.join(root, TARGET_REL)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == FUNC_NAME:
                    return item.lineno, item.end_lineno
    die("target function not found in source")


def build_question(def_line, first, last):
    return f"""Consider the pytest test class `{TEST_CLASS}` in the file `{TEST_FILE}` (pytest id `{TEST_FILE}::{TEST_CLASS}`). Run ALL of its test methods (every `test_...` method of the class, each identified by its pytest id `{TEST_FILE}::{TEST_CLASS}::<method_name>`; pytest runs them in alphabetical order, but the answer does not depend on order). The test methods call the target directly, sometimes several times each, with header values built from seeded `random.Random` generators.

Target function: the classmethod `{QUALNAME}` defined in `src/werkzeug/datastructures/range.py` (its `def` statement is on line {def_line}). Only this exact function's own frames count — NOT `Range.from_header`, `IfRange.from_header`, or any other `from_header`, and not lines of any function it calls (such as `werkzeug._internal._plain_int` or `ContentRange.__init__`).

An invocation is one call of `ContentRange.from_header` during the run. Aggregate over EVERY invocation in EVERY test method of the class (totals summed over all methods, not per method).

Executed line: a line counts once each time the Python interpreter reports a line event (as `sys.settrace` 'line' events do on CPython 3.11) for that line inside a frame of `ContentRange.from_header`. Consequences: a `try:` line is counted each time it is entered; an `except ValueError:` line is counted each time it is reached because a `ValueError` was raised inside its `try` block; an `if`/`else` test is counted on the `if` line each time its condition is evaluated (an `else:` line itself never produces an event); a `return` line is counted each time it executes. The `def` line ({def_line}) and the `@classmethod` decorator line are out of scope (call events are not line events). For a multi-line statement the event fires on the line where the statement begins; all other physical lines of it are reported with count 0.

Scope: every physical line from line {first} through line {last} inclusive (the line right after the `def` line through the function's last line, `return cls(units, start, stop + 1, length)`). Every one of these lines must appear exactly once in the answer, including docstring lines, blank lines, comment lines, `else:` lines, and lines that never execute — all of those are reported with `count` 0. Line numbers are absolute, 1-based line numbers in `src/werkzeug/datastructures/range.py` as it exists in the repository.

Answer format: a JSON object `{{"line_execution_counts": [...]}}` whose list contains one object per line in scope with exactly the keys `line` (int) and `count` (int, total number of executions, 0 if never executed), sorted by `line` ascending, with no duplicates."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=os.getcwd())
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        die(f"trace log empty: {args.trace_log}")

    def_line, end_line = find_target(args.root)
    first, last = def_line + 1, end_line

    counts = {ln: 0 for ln in range(first, last + 1)}
    n_calls = n_lines = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
                continue
            if m.group("func") != QUALNAME:
                continue
            ev = m.group("event")
            ln = int(m.group("line"))
            if ev == "call":
                n_calls += 1
            elif ev == "line":
                if ln not in counts:
                    die(f"line event outside function scope: {ln}")
                counts[ln] += 1
                n_lines += 1

    if n_calls == 0 or n_lines == 0:
        die("no events for ContentRange.from_header in trace")

    answer = {
        "line_execution_counts": [
            {"count": counts[ln], "line": ln} for ln in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(def_line, first, last),
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"calls={n_calls} line_events={n_lines} "
          f"distinct={sum(1 for v in counts.values() if v)}")
    print(json.dumps({str(d['line']): d['count'] for d in answer['line_execution_counts'] if d['count']}))


if __name__ == "__main__":
    main()
