#!/usr/bin/env python
"""Trace -> oracle for test_open_m6_calls.

Counts `call` events for every method defined directly in the body of
class ``Client`` in ``src/werkzeug/test.py``, aggregated over all test
methods of ``ClientFlowTest``.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "src/werkzeug/test.py"
MODULE = "werkzeug.test"
CLASS = "Client"
TARGET_FUNC = f"{MODULE}.{CLASS}.open"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<path>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the test class `ClientFlowTest` in "
    "`werkzeug_qa/test_open_m6_calls/files/testcase.py`, run with pytest as a whole "
    "(pytest id `werkzeug_qa/test_open_m6_calls/files/testcase.py::ClientFlowTest`, "
    "i.e. ALL of its test methods, in the order pytest collects them). The test drives werkzeug's test client, whose request entry point "
    "`werkzeug.test.Client.open` (file `src/werkzeug/test.py`) is reached only through "
    "the client's public helpers and its redirect-following machinery. "
    "Consider every method defined directly in the body of class `Client` in "
    "`src/werkzeug/test.py` (every `def` statement that is an immediate member of the "
    "class body, including `__init__` and other dunder methods and private "
    "underscore-prefixed methods; there are no properties or decorated methods in this "
    "class). Excluded: methods inherited from `object` or other classes, methods of any "
    "other class in that file (e.g. `EnvironBuilder`, `TestResponse`, `Cookie`), "
    "module-level functions (e.g. the module-level `run_wsgi_app`), any overriding methods "
    "defined outside `src/werkzeug/test.py`, and frames of nested functions, lambdas, "
    "comprehensions or generator expressions that appear inside those methods. "
    "For each in-scope method, count how many times it was invoked during the run of ALL "
    "test methods of the class, summed together (not per test method). One invocation = "
    "one Python `call` event for a frame executing that method's code object, regardless "
    "of who called it (the test itself, another `Client` method, or werkzeug internals), "
    "including transitive and repeated calls, and including invocations that end by "
    "raising an exception. None of the in-scope methods are generators or coroutines, so "
    "no resumption events arise. Methods that never ran must still be listed with "
    "`count: 0`. Identify each method by its dotted name `<module>.<class qualname>.<method>` "
    "where the module is the importable name `werkzeug.test` (not `src.werkzeug.test`); "
    "for example the constructor is written `werkzeug.test.Client.__init__`. The `file` "
    "field is the repo-relative path `src/werkzeug/test.py` for every entry. `count` is a "
    "JSON integer. Sort the list by `func` ascending using plain Python string comparison "
    "(code-point order, so names beginning with `_` sort after upper-case letters and "
    "before lower-case letters); qualnames are unique so no tie-break is needed. "
    "Answer as JSON of the form "
    "{\"invocation_counts\": [{\"count\": <int>, \"file\": \"src/werkzeug/test.py\", "
    "\"func\": \"werkzeug.test.Client.<method>\"}, ...]}."
)

TEMPLATE = {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_methods(repo_root: str) -> list[str]:
    path = os.path.join(repo_root, TARGET_FILE)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CLASS:
            return [
                f"{MODULE}.{CLASS}.{n.name}"
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    fail(f"class {CLASS} not found in {TARGET_FILE}")
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log empty: {args.trace_log}")

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    if not os.path.isfile(os.path.join(repo_root, TARGET_FILE)):
        repo_root = os.getcwd()
    methods = scope_methods(repo_root)
    counts = {m: 0 for m in methods}

    target_events = 0
    with open(args.trace_log, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            path = m.group("path").replace("\\", "/")
            if not path.endswith("/" + TARGET_FILE):
                continue
            func = m.group("func")
            if func == TARGET_FUNC:
                target_events += 1
            if m.group("event") == "call" and func in counts:
                counts[func] += 1

    if target_events == 0:
        fail(f"no trace events for {TARGET_FUNC}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": TARGET_FILE, "func": f}
            for f in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
