#!/usr/bin/env python
"""Derive the M6_InterProceduralCFG oracle for the optuna.importance._ped_anova package.

The scope (every module-level function and every method of every top-level class, in both
source files of the package) is read from the source with ``ast``; the number of ``call``
events of each in-scope function is counted from the trace, summed over all test methods of
the test class. Functions that never ran are reported with count 0.
"""
import argparse
import ast
from collections import Counter
import json
import os
import re
import sys

PKG_DIR = "optuna/importance/_ped_anova"
SOURCES = [
    PKG_DIR + "/evaluator.py",
    PKG_DIR + "/scott_parzen_estimator.py",
]
TARGET_QUALNAME = "optuna.importance._ped_anova.evaluator.PedAnovaImportanceEvaluator.evaluate"
TEST_FILE = "optuna_qa/evaluator_evaluate_m6_calls/files/testcase.py"
TEST_CLASS = "TestPedAnovaEvaluateCallGraph"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test class `" + TEST_CLASS + "` in the file `" + TEST_FILE + "`, run "
    "as `pytest " + TEST_FILE + "::" + TEST_CLASS + "` (i.e. ALL test methods of the class, "
    "each identified by its pytest id `" + TEST_FILE + "::" + TEST_CLASS + "::<method name>`). "
    "Every test method calls `" + TARGET_QUALNAME + "` (defined in `" + PKG_DIR
    + "/evaluator.py`) directly on a study it builds.\n\n"
    "Scope: the two source files of the package directory `" + PKG_DIR + "/`, namely `"
    + SOURCES[0] + "` (module `optuna.importance._ped_anova.evaluator`) and `" + SOURCES[1]
    + "` (module `optuna.importance._ped_anova.scott_parzen_estimator`); `__init__.py` "
    "contains no functions. INCLUDED in the scope: every function defined by a `def` "
    "statement at the top level of either file, and every method defined by a `def` "
    "statement directly in the body of any class defined at the top level of either file "
    "(including `__init__`, private underscore-prefixed methods, and methods that are never "
    "called). EXCLUDED: lambdas (including lambdas passed in by the tests), comprehension "
    "and generator-expression frames, module-level code, methods inherited from base "
    "classes but not defined in these files (e.g. anything from "
    "`optuna/importance/_base.py`), functions merely imported into these modules from "
    "elsewhere (e.g. `optuna.samplers._tpe.sampler._split_complete_trials_multi_objective`, "
    "the `_Batched*`/`_MixtureOfProductDistribution` classes, distribution methods), and "
    "same-named functions in any other file.\n\n"
    "Invocation: one invocation is one Python `call` event for a frame executing that "
    "function's code object (as seen by `sys.settrace`), i.e. one entry into the function. "
    "Calls made from ANY frame count: directly from the tests, from other in-scope "
    "functions, from inside comprehensions, transitively, or recursively. Instantiating a "
    "class counts as one invocation of its `__init__` defined in these files. None of the "
    "in-scope functions is a generator or coroutine, so there are no resumption events. A "
    "call that later exits by raising an exception still counts. Count across ALL test "
    "methods of the class combined (sum over the whole class run, not per method); "
    "`setUp`/`tearDown` and test-module helpers are not in scope but any in-scope calls "
    "they cause count. A function in scope that never executes in any test method has "
    "count 0.\n\n"
    "Answer format: a JSON object `{\"invocation_counts\": [...]}` whose list contains exactly "
    "one object per in-scope function, with keys `count` (int, the total number of "
    "invocations), `file` (str, the repo-relative path of the file that defines the "
    "function, e.g. `" + SOURCES[1] + "`), and `func` (str, the dotted name "
    "`<module>.<qualname>` where qualname is Python's `__qualname__`, e.g. "
    "`optuna.importance._ped_anova.evaluator._QuantileFilter.filter`). Sort the list by "
    "`func` ascending using plain Python string ordering (code-point order; note that `_` "
    "sorts after uppercase letters and before lowercase letters). No two entries share a "
    "`func`, so no further tie-break is needed. Do not omit zero-count functions and do not "
    "add entries outside the scope."
)

TEMPLATE = {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def module_of(rel: str) -> str:
    return rel[: -len(".py")].replace("/", ".")


def scope_functions(rel: str) -> list[str]:
    with open(rel, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=rel)
    mod = module_of(rel)
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.append(node.name + "." + sub.name)
    if not names:
        fail(f"no functions found in {rel}")
    return [mod + "." + n for n in names]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    func_to_file = {}
    for rel in SOURCES:
        if not os.path.isfile(rel):
            fail(f"source not found: {rel}")
        for func in scope_functions(rel):
            func_to_file[func] = rel

    counts: Counter = Counter()
    target_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            path = m.group("file").replace("\\", "/")
            func = m.group("func")
            if func not in func_to_file or not path.endswith(func_to_file[func]):
                continue
            if func == TARGET_QUALNAME:
                target_events += 1
            if m.group("event") == "call":
                counts[func] += 1

    if target_events == 0 or counts[TARGET_QUALNAME] == 0:
        fail(f"no trace events for target {TARGET_QUALNAME}")

    answer = {
        "invocation_counts": [
            {"count": counts[func], "file": func_to_file[func], "func": func}
            for func in sorted(func_to_file)
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
