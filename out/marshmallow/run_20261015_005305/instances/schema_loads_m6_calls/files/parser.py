#!/usr/bin/env python
"""Trace -> oracle.json for schema_loads_m6_calls (M6_InterProceduralCFG)."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "src/marshmallow/schema.py"
MODULE = "marshmallow.schema"
CLASS = "Schema"
TARGET = f"{MODULE}.{CLASS}.loads"
TEST_FILE = "marshmallow_qa/schema_loads_m6_calls/files/testcase.py"
TEST_CLASS = "TestSchemaLoadsCalls"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CLASS:
            names = [
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if not names:
                fail(f"class {CLASS} in {REL_FILE} has no methods")
            return sorted({f"{MODULE}.{CLASS}.{n}" for n in names})
    fail(f"class {CLASS} not found in {REL_FILE}")


QUESTION = f"""Consider the test class `{TEST_CLASS}` in `{TEST_FILE}`, run with `pytest {TEST_FILE}::{TEST_CLASS}` (all of its test methods, in the order pytest collects them; the answer aggregates over ALL of them). Every test method calls `marshmallow.schema.Schema.loads` (file `{REL_FILE}`) directly, on various `Schema` subclasses.

Scope: every function/method whose `def` statement appears DIRECTLY in the body of class `{CLASS}` in `{REL_FILE}` (the class named exactly `{CLASS}`, not `SchemaMeta` or `SchemaOpts`, and not any module-level function). This includes `__init__`, dunder methods, classmethods, staticmethods and name-mangled private methods defined there. Excluded: nested functions/closures/lambdas defined inside those methods, comprehension and generator-expression frames, methods of any other class (including the `Schema` subclasses defined in the test file — if a test subclass overrides a method, a call that resolves to the override does NOT count for `{CLASS}`'s version), and functions in other files (e.g. `src/marshmallow/fields.py`, `src/marshmallow/decorators.py`). A call made on a subclass instance that resolves (by inheritance) to the method defined in `{CLASS}`'s body DOES count for that `{CLASS}` method.

Identity: `func` is `marshmallow.schema.` followed by the function's `__qualname__` as Python reports it, e.g. `marshmallow.schema.Schema.some_method` (format example only). Name-mangled methods use their source spelling (the qualname is not mangled), e.g. a method written `def __helper(self)` in the class would be `marshmallow.schema.Schema.__helper`. `file` is the repo-relative path `{REL_FILE}` for every entry.

Counting: one invocation = one Python `call` event (a new frame created for that function's code object), regardless of who called it (the test, another `{CLASS}` method, field code such as `Nested`/`List`, recursion for `many=True` or nested schemas, decorators' hooks, etc.) and regardless of whether the call returns normally or raises. Recursive/re-entrant calls each count. None of the in-scope functions are generators or coroutines, so no resumption issue arises. Count only calls made while the test methods run (including schema instantiation and any schema classes created lazily during a test, e.g. by `Nested` with a dict); calls during module import / test-module class-body definitions do not count.

Zero rule: every in-scope function appears exactly once in the answer, with `count: 0` if it never ran.

Aggregation: counts are summed across all test methods of the class (whether each method's `loads` call succeeds or raises).

Output: `{{"invocation_counts": [{{"count": int, "file": str, "func": str}}, ...]}}`, sorted by `func` ascending using plain Python string ordering (code-point order, so `_` sorts after uppercase letters and before lowercase letters); qualnames are unique, so no tie-break is needed."""


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
