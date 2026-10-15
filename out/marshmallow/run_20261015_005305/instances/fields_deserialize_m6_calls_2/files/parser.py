#!/usr/bin/env python
"""Trace -> oracle.json for fields_deserialize_m6_calls_2 (M6_InterProceduralCFG)."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "src/marshmallow/fields.py"
MODULE = "marshmallow.fields"
CLASSES = ["_TemporalField", "DateTime", "NaiveDateTime", "AwareDateTime", "Time", "Date"]
TARGET = f"{MODULE}._TemporalField._deserialize"
TEST_FILE = "marshmallow_qa/fields_deserialize_m6_calls_2/files/testcase.py"
TEST_CLASS = "TestTemporalDeserializeCalls"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>/\S+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in CLASSES:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.setdefault(node.name, []).append(item.name)
    missing = [c for c in CLASSES if c not in found]
    if missing:
        fail(f"classes not found in {REL_FILE}: {missing}")
    return sorted({f"{MODULE}.{c}.{m}" for c, ms in found.items() for m in ms})


QUESTION = f"""Consider the test class `{TEST_CLASS}` in `{TEST_FILE}`, run with `pytest {TEST_FILE}::{TEST_CLASS}` (all 12 of its test methods, in the order pytest collects them; the answer aggregates over ALL of them). The schemas in these tests eventually reach `marshmallow.fields._TemporalField._deserialize` (file `{REL_FILE}`) through `Field.deserialize` and container fields.

Scope: every function/method whose `def` appears DIRECTLY in the class body of one of these six classes in `{REL_FILE}`: `_TemporalField`, `DateTime`, `NaiveDateTime`, `AwareDateTime`, `Time`, `Date`. This includes `__init__`, dunder methods, staticmethods and abstract methods defined there (whether or not they can ever execute). Inherited methods are NOT re-listed under a subclass: a method belongs only to the class whose body textually defines it (e.g. a call to `DateTime(...).method` that resolves to `_TemporalField.method` counts toward `_TemporalField.method`). Methods of other classes (e.g. `Field`, `List`, `Schema`) and functions in other files are out of scope. There are no nested functions, lambdas, or properties inside these six class bodies, so none are tracked.

Identity: `func` is the dotted `module.qualname` of the function, where the module is `marshmallow.fields`, e.g. `marshmallow.fields.Field.serialize` (format example only; that method is not in scope). `file` is the repo-relative path `{REL_FILE}` for every entry.

Counting: one invocation = one Python `call` event (a new frame created for that function's code object), regardless of who called it (the test, another in-scope method via `super()`, marshmallow internals, a container field, etc.) and regardless of whether the call returns normally or raises. Recursive/re-entrant calls each count. None of the in-scope functions are generators, so no resumption issue arises. Count only during the execution of the test methods themselves (class bodies of the test-local Schema classes are evaluated inside the test method and so any calls they trigger count; module import of marshmallow does not).

Zero rule: every in-scope function appears exactly once in the answer, with `count: 0` if it never ran.

Aggregation: counts are summed across all test methods of the class.

Output: `{{"invocation_counts": [{{"count": int, "file": str, "func": str}}, ...]}}`, sorted by `func` ascending (plain Python string ordering, so uppercase letters sort before `_`); qualnames are unique, so no tie-break is needed."""


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
        fail("trace log is empty")

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / REL_FILE
    if not source_path.is_file():
        source_path = Path("/testbed") / REL_FILE
    scope = scope_functions(source_path)
    counts = {f: 0 for f in scope}

    target_events = 0
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        func = m.group("func")
        if func == TARGET:
            target_events += 1
        if m.group("event") == "call" and func in counts:
            counts[func] += 1

    if target_events == 0:
        fail(f"no trace events for target {TARGET}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": REL_FILE, "func": f} for f in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
