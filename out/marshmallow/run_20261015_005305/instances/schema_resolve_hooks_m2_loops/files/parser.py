#!/usr/bin/env python
"""Derive the M2_Loops oracle for SchemaMeta.resolve_hooks from a trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_QUAL = "marshmallow.schema.SchemaMeta.resolve_hooks"
TEST_REL = "marshmallow_qa/schema_resolve_hooks_m2_loops/files/testcase.py"
TEST_CLASS = "ResolveHooksLoopTest"

LINE_RE = re.compile(r"\s(\S+):(\d+) (\S+) event=(\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loops(src_path):
    tree = ast.parse(Path(src_path).read_text(encoding="utf-8"))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "SchemaMeta":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "resolve_hooks":
                    outer = [n for n in fn.body if isinstance(n, ast.For)]
                    if len(outer) != 1:
                        fail("expected exactly one top-level for loop")
                    outer = outer[0]
                    inner = [n for n in outer.body if isinstance(n, ast.For)]
                    if len(inner) != 1:
                        fail("expected exactly one directly nested for loop")
                    inner = inner[0]
                    first = inner.body[0]
                    if not isinstance(first, ast.Try) or not first.body:
                        fail("expected inner loop body to start with try")
                    return outer, inner, first.body[0]
    fail("SchemaMeta.resolve_hooks not found in source")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path(__file__).resolve().parents[3] / TARGET_REL
    if not src.is_file():
        src = Path("/testbed") / TARGET_REL
    outer, inner, counted = find_loops(src)
    counted_line = counted.lineno
    if counted.end_lineno != counted_line:
        fail("counted statement unexpectedly spans multiple lines")

    calls = 0
    events = 0
    iterations = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        path, lineno, qual, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if not path.replace("\\", "/").endswith(TARGET_REL) or qual != TARGET_QUAL:
            continue
        events += 1
        if event == "call":
            calls += 1
        elif event == "line" and lineno == counted_line:
            iterations += 1

    if events == 0 or calls == 0:
        fail("trace contains zero events for the target function")
    if iterations == 0:
        fail("inner loop never iterated")

    question = (
        f"Run ALL test methods of the class `{TEST_CLASS}` in `{TEST_REL}` "
        f"(e.g. `pytest {TEST_REL}::{TEST_CLASS}`, all 12 `test_*` methods in a single "
        "pytest process, identified by their pytest ids; the answer aggregates over "
        "ALL of them and does not depend on their execution order). Consider the classmethod-style metaclass method "
        f"`SchemaMeta.resolve_hooks` (dotted name `{TARGET_QUAL}`) defined in "
        f"`{TARGET_REL}`. It contains an outer loop `for attr_name in dir(cls):` "
        f"(line {outer.lineno}) and, directly nested inside it, an inner loop "
        f"`for parent in mro:` (line {inner.lineno}). Define one iteration of the "
        "inner loop as one execution of its body's first real statement, "
        f"`attr = parent.__dict__[attr_name]` (line {counted_line}); every inner-loop "
        "iteration executes that line exactly once, whether the dictionary lookup "
        "succeeds (followed by `break`) or raises KeyError (followed by `continue`). "
        "Count these iterations summed over EVERY invocation of `resolve_hooks` that "
        "happens while the test methods execute (inside the test method bodies, "
        "i.e. not during module import/collection), and over all outer-loop "
        "iterations of each invocation. An invocation is one call of the function; "
        "this includes BOTH the explicit `resolve_hooks()` calls written in the "
        "tests AND the implicit calls made by `SchemaMeta.__init__` whenever a "
        "schema class is created during a test (via `SchemaMeta(...)`, a subclass of "
        "`SchemaMeta`, or `Schema.from_dict`). Use the repository source exactly as "
        "checked in and the Python interpreter of this environment (the result of "
        "`dir()` depends on it). Answer with a JSON object with the single key "
        "`total_iterations` whose value is a JSON integer (the plain base-10 total, "
        "e.g. {\"total_iterations\": 4321})."
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": iterations},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"]))
    print(f"invocations={calls} target_events={events}")


if __name__ == "__main__":
    main()
