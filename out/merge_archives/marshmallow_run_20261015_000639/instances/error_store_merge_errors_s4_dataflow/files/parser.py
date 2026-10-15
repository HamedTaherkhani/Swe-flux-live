#!/usr/bin/env python
"""Trace -> oracle.json for error_store_merge_errors_s4_dataflow (S4_DataFlow)."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/error_store.py"
TARGET_FUNC = "merge_errors"
TARGET_QUAL = "marshmallow.error_store.merge_errors"
TEST_PATH = "marshmallow_qa/error_store_merge_errors_s4_dataflow/files/testcase.py"
TEST_CLASS = "MergeErrorsDataFlowTest"
TEST_METHOD = "test_load_many_collects_errors"
TRACKED = ("errors1", "errors2", "key", "val")

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def analyze_source(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC:
            fn = node
    if fn is None:
        fail("target function not found in source")
    params = [a.arg for a in fn.args.args]
    loads, stores = {}, {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id in TRACKED:
            bucket = loads if isinstance(node.ctx, ast.Load) else stores
            bucket.setdefault(node.lineno, set()).add(node.id)
    return fn.lineno, params, loads, stores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path.cwd() / TARGET_REL
    if not src.is_file():
        src = Path(__file__).resolve().parents[3] / TARGET_REL
    def_line, params, loads, stores = analyze_source(src)

    stack = []  # per-frame dict var -> current def line
    pairs = set()
    calls = 0
    line_events = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_QUAL:
            continue
        event, line = m.group("event"), int(m.group("line"))
        if event == "call":
            calls += 1
            stack.append({p: def_line for p in params if p in TRACKED})
        elif event == "line":
            if not stack:
                fail("line event outside of a call frame")
            line_events += 1
            frame = stack[-1]
            for var in sorted(loads.get(line, ())):
                if var in frame:
                    pairs.add((var, frame[var], line))
            for var in sorted(stores.get(line, ())):
                frame[var] = line
        elif event == "return":
            if not stack:
                fail("return event outside of a call frame")
            stack.pop()
    if calls == 0 or line_events == 0:
        fail("no events for the target function in the trace")
    if stack:
        fail("unbalanced call/return events in trace")

    answer = [
        {"def_line": d, "use_line": u, "variable": v} for v, d, u in sorted(pairs)
    ]
    question = (
        f"Run the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (test class "
        f"`{TEST_CLASS}`, its single test method `{TEST_METHOD}`). During that test, the "
        f"function `marshmallow.error_store.merge_errors` defined in `{TARGET_REL}` is "
        "invoked many times (reached via `ErrorStore.store_error` during `Schema.load`, "
        "and recursively by itself). Considering ALL invocations of `merge_errors` during "
        "the test run (every call, including recursive calls; each call is its own frame "
        "with its own local variables), report every unique dynamically observed def-use "
        "pair for exactly these local variable names: `errors1`, `errors2`, `key`, `val`. "
        "Definitions: a 'def' of a variable is a binding of the bare name: the parameters "
        "`errors1` and `errors2` are defined at the line of the `def merge_errors(...)` "
        "statement when the call starts; the `for` loop header line binds `key` and `val` "
        "(a new def on every iteration, all attributed to the header line). Item/subscript "
        "assignment such as `errors1[key] = ...` or `errors2[SCHEMA] = ...` is NOT a def of "
        "`errors1`/`errors2` (it mutates the object); instead it is a USE of that variable "
        "(the name is read), and any tracked name inside the subscript or right-hand side "
        "is also a use. A 'use' is any read of the bare variable name on a source line that "
        "actually executed (e.g. in a condition, call argument, method receiver like "
        "`errors1.extend`, subscript, membership test, or return expression). (There are no "
        "augmented assignments or comprehensions involving these names in this function; if "
        "there were, `x += 1` would count as a use of the old def and a new def on that line.) "
        "A pair (variable, def_line, use_line) is observed when, in some invocation, the "
        "value bound at def_line is read at use_line before that variable is redefined in "
        "the same frame. Uses are attributed to the line on which the statement begins, "
        "which here is always the line containing the name. Values from different frames "
        "never pair with each other. All line numbers are absolute, 1-based line numbers "
        f"in `{TARGET_REL}` as it exists in the repository. Return a JSON object with a "
        "single key `observed_def_use_pairs` whose value is a list of objects, each with "
        "exactly the keys `variable` (string, the bare variable name), `def_line` (integer) "
        "and `use_line` (integer). Each distinct triple appears exactly once (duplicates "
        "across iterations/invocations removed). Sort the list ascending by `variable` "
        "(plain string comparison), then by `def_line`, then by `use_line`."
    )
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": answer},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calls={calls} line_events={line_events} pairs={len(answer)}")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
