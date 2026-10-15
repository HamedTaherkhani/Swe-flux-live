#!/usr/bin/env python
"""Parse the trace log into per-function invocation counts for every
function/method defined in src/werkzeug/debug/repr.py."""

import argparse
import ast
import json
import os
import re
import sys

REL_FILE = "src/werkzeug/debug/repr.py"
MODULE = "werkzeug.debug.repr"
TARGET = f"{MODULE}.DebugReprGenerator.dispatch_repr"

LINE_RE = re.compile(r" (\S+\.py):(\d+) (\S+) event=(\w+)")

QUESTION = (
    "Run the whole test class `TestDebugReprScenarios` in "
    "`werkzeug_qa/repr_dispatch_repr_m6_calls/files/testcase.py` with pytest "
    "(pytest id `werkzeug_qa/repr_dispatch_repr_m6_calls/files/testcase.py::TestDebugReprScenarios`; "
    "all 13 `test_*` methods, which all pass). These tests exercise the HTML debug-repr machinery whose central "
    "type-dispatch method is `werkzeug.debug.repr.DebugReprGenerator.dispatch_repr` in "
    "`src/werkzeug/debug/repr.py`.\n\n"
    "Scope: consider EVERY function and method defined with `def` anywhere in the file "
    "`src/werkzeug/debug/repr.py`: all module-level functions, all methods of every class defined in that file "
    "(including dunder methods such as `__init__`, `__repr__`, `__call__`), and functions nested inside other "
    "functions (closures). Lambdas, comprehension frames (list/dict/set comprehensions, generator expressions), "
    "class bodies and the module body are NOT in scope. Methods inherited from `object` or from builtins, and "
    "functions/methods defined in other files (including the test file), are NOT in scope even when invoked "
    "from in-scope code. Class attributes that are produced by calling a factory (e.g. assigned function objects "
    "returned from another function) are not separate scope entries: a nested function is ONE entry identified by "
    "its definition, no matter how many function objects are created from it or under which attribute names they "
    "are called.\n\n"
    "Identity: `func` is the module name `werkzeug.debug.repr` followed by a dot and the function's Python "
    "`__qualname__` (as in `code.co_qualname`), e.g. a method `bar` of a class `Foo` in that file would be "
    "`werkzeug.debug.repr.Foo.bar`, and a function `inner` nested in a module-level function `outer` would be "
    "`werkzeug.debug.repr.outer.<locals>.inner`. `file` is always the repo-relative path `src/werkzeug/debug/repr.py`.\n\n"
    "Counting: `count` is the number of times a new Python frame for that function is entered (one `call` event "
    "per invocation) while the test methods are executing, including invocations made indirectly, recursively, "
    "via implicit protocols (e.g. `repr()`/`!r` formatting calling a `__repr__`), or from any caller. There are "
    "no generators or coroutines in scope, so no resumption is ever counted. Calls that happen outside the test "
    "methods' execution (e.g. while importing modules, collecting tests, or in class-level setup at import time) "
    "are NOT counted. Counts are summed over ALL 13 test methods of the class (not per method). Every in-scope "
    "function must be listed, including those never invoked, which get `count: 0`.\n\n"
    "Answer format: a JSON object `{\"invocation_counts\": [...]}` whose list contains one object "
    "`{\"count\": <int>, \"file\": <str>, \"func\": <str>}` per in-scope function, sorted by `func` ascending using "
    "plain Python string ordering (code-point order; qualnames are unique so no tie-break is needed). Use the "
    "Python interpreter installed in the repository's environment."
)


def scope_functions(source_path):
    tree = ast.parse(open(source_path, encoding="utf-8").read())
    out = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}{child.name}"
                out.append(q)
                walk(child, f"{q}.<locals>.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return sorted(f"{MODULE}.{q}" for q in out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=os.path.join(os.getcwd(), REL_FILE))
    args = ap.parse_args()

    if not os.path.exists(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    scope = scope_functions(args.source)
    counts = {f: 0 for f in scope}
    target_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for line in fh:
            m = LINE_RE.search(line)
            if not m:
                continue
            path, _lineno, func, event = m.groups()
            if not path.replace("\\", "/").endswith(REL_FILE):
                continue
            if func == TARGET:
                target_events += 1
            if event != "call":
                continue
            if func not in counts:
                sys.exit(f"ERROR: traced function outside computed scope: {func}")
            counts[func] += 1

    if target_events == 0:
        sys.exit("ERROR: no trace events for target dispatch_repr")

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
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
