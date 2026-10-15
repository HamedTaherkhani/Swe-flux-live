#!/usr/bin/env python
"""Derive the M6_InterProceduralCFG oracle for optuna.visualization._parallel_coordinate.

The scope (every top-level ``def`` of the module) is read from the source with ``ast``; the
number of ``call`` events of each in-scope function is counted from the trace, summed over all
test methods of the test class. Functions that never ran are reported with count 0.
"""
import argparse
import ast
from collections import Counter
import json
import os
import re
import sys

TARGET_REL = "optuna/visualization/_parallel_coordinate.py"
MODULE = "optuna.visualization._parallel_coordinate"
TARGET_QUALNAME = MODULE + "._get_parallel_coordinate_plot"
TEST_FILE = "optuna_qa/parallel_coordinate_get_parallel_coordinate_plot_m6_calls/files/testcase.py"
TEST_CLASS = "TestParallelCoordinateCallGraph"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test class `" + TEST_CLASS + "` in the file `" + TEST_FILE + "`, run "
    "as `pytest " + TEST_FILE + "::" + TEST_CLASS + "` (i.e. ALL test methods of the class, "
    "each identified by its pytest id `" + TEST_FILE + "::" + TEST_CLASS + "::<method name>`). "
    "The tests drive `optuna.visualization.plot_parallel_coordinate`, which builds an info "
    "object and then renders it with `" + TARGET_QUALNAME + "` (defined in `" + TARGET_REL
    + "`).\n\n"
    "Scope: every function defined by a `def` statement at the TOP LEVEL of the module file `"
    + TARGET_REL + "` (module `" + MODULE + "`), i.e. every module-level function of that "
    "file, whether public or underscore-prefixed, and whether or not it is ever called. "
    "EXCLUDED from the scope: functions nested inside other functions (closures / local "
    "`def`s), lambdas, comprehension and generator-expression frames, the classes defined in "
    "the file and any methods of them (including NamedTuple-generated methods, `__new__`, "
    "`_replace`, `__init__` and other dunders), functions merely imported into the module "
    "from elsewhere (e.g. helpers from `optuna/visualization/_utils.py`), and same-named "
    "functions in any other file (e.g. `optuna/visualization/matplotlib/_parallel_coordinate.py`).\n\n"
    "Invocation: one invocation is one Python `call` event for a frame executing that "
    "function's code object (as seen by `sys.settrace`), i.e. one entry into the function. "
    "Calls made from ANY frame count: directly from the tests, from other functions in the "
    "module, from inside comprehensions/generator expressions or lambdas, transitively, or "
    "recursively. None of the in-scope functions is a generator or coroutine, so there are "
    "no resumption events. A call that later exits by raising an exception still counts. "
    "Count across ALL test methods of the class combined (sum over the whole class run, not "
    "per method); a function that never executes in any test method has count 0.\n\n"
    "Answer format: a JSON object `{\"invocation_counts\": [...]}` whose list contains exactly "
    "one object per in-scope function, with keys `count` (int, the total number of "
    "invocations), `file` (str, the repo-relative path `" + TARGET_REL + "`, identical for "
    "every entry), and `func` (str, the dotted qualified name `<module>.<qualname>`, e.g. "
    "`optuna.visualization._parallel_coordinate.plot_parallel_coordinate`). Sort the list by "
    "`func` ascending using plain Python string ordering (code-point order; note that `_` "
    "sorts after uppercase letters and before lowercase letters). No two entries share a "
    "`func`, so no further tie-break is needed. Do not omit zero-count functions and do not "
    "add entries outside the scope."
)

TEMPLATE = {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(source_path: str) -> list[str]:
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not names:
        fail("no top-level functions found in target source")
    return sorted(MODULE + "." + name for name in names)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=TARGET_REL)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")
    if not os.path.isfile(args.source):
        fail(f"target source not found: {args.source}")

    scope = scope_functions(args.source)
    scope_set = set(scope)

    counts: Counter = Counter()
    target_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
                continue
            func = m.group("func")
            if func == TARGET_QUALNAME:
                target_events += 1
            if m.group("event") == "call" and func in scope_set:
                counts[func] += 1

    if target_events == 0 or counts[TARGET_QUALNAME] == 0:
        fail(f"no trace events for target {TARGET_QUALNAME}")

    answer = {
        "invocation_counts": [
            {"count": counts[func], "file": TARGET_REL, "func": func} for func in scope
        ]
    }
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
