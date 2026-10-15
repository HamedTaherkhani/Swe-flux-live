#!/usr/bin/env python
"""Parse the line trace of Schema._do_load into per-line execution counts."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_CLASS = "Schema"
TARGET_NAME = "_do_load"
TARGET_QUAL = "marshmallow.schema.Schema._do_load"
TEST_PATH = "marshmallow_qa/schema_do_load_m1_cfg/files/testcase.py"
TEST_CLASS = "TestDoLoadPaths"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_function_span(src_path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_NAME:
                    return item.lineno, item.end_lineno
    fail(f"could not locate {TARGET_CLASS}.{TARGET_NAME} in {src_path}")


def build_question(def_line, first, last):
    return (
        f"In the repository, the test file `{TEST_PATH}` defines the unittest class "
        f"`{TEST_CLASS}` with thirteen test methods (`test_01_...` through `test_13_...`). "
        f"Run ALL test methods of this class with pytest (pytest id "
        f"`{TEST_PATH}::{TEST_CLASS}`), in pytest's default order. None of the tests "
        f"call the target directly; it is reached through `Schema.load`, `Schema.loads`, "
        f"`Schema.validate`, and through nested schemas loaded by `fields.Nested` "
        f"(including nested fields inside `fields.List`).\n\n"
        f"Target function: `{TARGET_QUAL}` (i.e. `Schema._do_load`), defined in "
        f"`{TARGET_REL}` with its `def` statement at line {def_line}; the function "
        f"spans lines {def_line}-{last}.\n\n"
        f"Question: across the whole test run (summing over ALL invocations of "
        f"`Schema._do_load`, from any schema instance and any call path, in ALL test "
        f"methods of the class), how many times did each line of the function execute?\n\n"
        f"Definitions:\n"
        f"- An 'execution' of line L is one `'line'` event delivered by Python's "
        f"`sys.settrace` line tracer (the CPython interpreter installed in this "
        f"environment) for a frame running the code object of `Schema._do_load`, with "
        f"`frame.f_lineno == L`. Only `'line'` events count; `'call'`, `'return'` and "
        f"`'exception'` events are NOT counted. Events from other functions (callees "
        f"such as `_deserialize`, hook methods, `handle_error`, nested frames) do not "
        f"count, but every separate invocation of `_do_load` (including recursive "
        f"invocations from nested schemas) does.\n"
        f"- Report exactly what the tracer delivers: for a multi-line statement, the "
        f"event usually fires on the line where the statement begins, but if the "
        f"interpreter also delivers line events on continuation lines (or returns to "
        f"the first line of a statement after visiting a continuation line), each "
        f"such event is counted on the line it reports. The same line may therefore "
        f"be counted more than once per invocation.\n"
        f"- Scope: every physical line number from {first} to {last} inclusive (that "
        f"is, all lines after the `def` line {def_line} up to the function's last "
        f"line). The `def` line {def_line} itself is excluded. Lines in scope that "
        f"never receive a line event - parameter-list continuation lines, docstring "
        f"lines, blank lines, comment-only lines, continuation "
        f"lines with no event, and code that never ran - MUST still be listed, with "
        f"`count` 0. The list therefore has exactly {last - first + 1} entries.\n"
        f"- Line numbers are absolute, 1-based line numbers in `{TARGET_REL}` as it "
        f"exists in the repository (unmodified).\n\n"
        f"Answer format: a JSON object with a single key `line_execution_counts`, whose "
        f"value is a list of objects `{{\"count\": <int>, \"line\": <int>}}`, one per "
        f"line in scope, sorted by `line` ascending (no duplicates). `count` is a "
        f"non-negative JSON integer (the total over all invocations in all test methods)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {trace_path}")

    src_path = Path(__file__).resolve().parents[3] / TARGET_REL
    if not src_path.is_file():
        src_path = Path.cwd() / TARGET_REL
    def_line, last = find_function_span(src_path)
    first = def_line + 1

    counts = Counter()
    calls = 0
    line_events = 0
    for raw in text.splitlines():
        m = EVENT_RE.search(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_QUAL:
            continue
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "line":
            line_events += 1
            counts[int(m.group("line"))] += 1

    if calls == 0 or line_events == 0:
        fail(f"no events for {TARGET_QUAL} in trace (calls={calls}, lines={line_events})")
    outside = sorted(ln for ln in counts if ln < first or ln > last)
    if outside:
        fail(f"line events outside function span: {outside}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(ln, 0), "line": ln} for ln in range(first, last + 1)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(def_line, first, last),
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calls={calls} line_events={line_events} distinct_lines={len(counts)}")
    for ln in range(first, last + 1):
        if counts.get(ln):
            print(f"  {ln}: {counts[ln]}")


if __name__ == "__main__":
    main()
