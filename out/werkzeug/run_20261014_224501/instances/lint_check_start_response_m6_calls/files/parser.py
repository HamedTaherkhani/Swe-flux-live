#!/usr/bin/env python
"""Trace -> oracle for lint_check_start_response_m6_calls.

Counts `call` events for every function and method (including nested
functions) defined in ``src/werkzeug/middleware/lint.py``, aggregated over
all test methods of ``CheckStartResponseFlowTest``.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "src/werkzeug/middleware/lint.py"
MODULE = "werkzeug.middleware.lint"
TARGET_FUNC = f"{MODULE}.LintMiddleware.check_start_response"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<path>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the test class `CheckStartResponseFlowTest` in "
    "`werkzeug_qa/lint_check_start_response_m6_calls/files/testcase.py`, run with pytest "
    "as a whole (pytest id "
    "`werkzeug_qa/lint_check_start_response_m6_calls/files/testcase.py::CheckStartResponseFlowTest`, "
    "i.e. ALL of its test methods, in the order pytest collects them). The tests call "
    "`werkzeug.middleware.lint.LintMiddleware.check_start_response` (file "
    "`src/werkzeug/middleware/lint.py`) directly with generated inputs, under various "
    "`warnings` filters (note that a warning filtered as \"error\" makes `warn(...)` raise "
    "the warning as an exception). "
    "Scope: every function and method whose `def` statement appears anywhere in "
    "`src/werkzeug/middleware/lint.py` — all module-level functions, all methods of every "
    "class defined in that file (including `__init__` and all other dunder methods), and "
    "nested functions defined inside those methods (closures). Excluded: methods inherited "
    "from base classes or from `object` (e.g. the warning classes in this file define no "
    "methods of their own, so they contribute nothing), anything defined in other files "
    "(e.g. `werkzeug.datastructures.Headers` methods, `warnings.warn`, `urlparse`), class "
    "bodies, module bodies, lambdas, comprehensions and generator expressions. "
    "Only execution that happens while the test methods themselves run counts (module "
    "import / test collection is not part of any test method). "
    "For each in-scope function, count how many times it was invoked, summed over ALL test "
    "methods of the class (not per method). One invocation = one Python `call` event for a "
    "frame executing that function's code object, regardless of who called it (the test "
    "directly, or another lint.py function transitively), including invocations that end "
    "by raising or propagating an exception. None of the in-scope functions are generators "
    "or coroutines, so no resumption events arise. In-scope functions that never ran must "
    "still be listed with `count: 0`. "
    "Identify each function by its dotted name `<module>.<__qualname__>`, where the module "
    "is the importable name `werkzeug.middleware.lint` (not `src.werkzeug.middleware.lint`) "
    "and the qualname is Python's `__qualname__` (nested functions include the "
    "`<locals>` segment); for example the constructor of the input-stream wrapper is "
    "written `werkzeug.middleware.lint.InputStream.__init__`. The `file` field is the "
    "repo-relative path `src/werkzeug/middleware/lint.py` for every entry. `count` is a "
    "JSON integer. Sort the list by `func` ascending using plain Python string comparison "
    "(code-point order); qualnames are unique so no tie-break is needed. "
    "Answer as JSON of the form "
    "{\"invocation_counts\": [{\"count\": <int>, \"file\": \"src/werkzeug/middleware/lint.py\", "
    "\"func\": \"werkzeug.middleware.lint.<qualname>\"}, ...]}."
)

TEMPLATE = {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(repo_root: str) -> list[str]:
    path = os.path.join(repo_root, TARGET_FILE)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out: list[str] = []

    def visit(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{node.name}"
                out.append(qual)
                visit(node.body, f"{qual}.<locals>.")
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    sub = getattr(node, field, None) or []
                    for s in sub:
                        if isinstance(s, ast.ExceptHandler):
                            visit(s.body, prefix)
                    visit([s for s in sub if not isinstance(s, ast.ExceptHandler)], prefix)

    visit(tree.body, "")
    return [f"{MODULE}.{q}" for q in out]


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
    funcs = scope_functions(repo_root)
    if len(set(funcs)) != len(funcs):
        fail("duplicate qualnames in scope")
    counts = {f: 0 for f in funcs}

    target_events = 0
    unknown: set[str] = set()
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
            if m.group("event") == "call":
                if func in counts:
                    counts[func] += 1
                else:
                    unknown.add(func)

    if target_events == 0:
        fail(f"no trace events for {TARGET_FUNC}")
    if unknown:
        fail(f"call events for functions outside the AST scope: {sorted(unknown)}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": TARGET_FILE, "func": f} for f in sorted(counts)
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
