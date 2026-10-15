#!/usr/bin/env python
"""Trace -> oracle.json for cmaes_init_optimizer_s4_dataflow (S4_DataFlow)."""

import argparse
import ast
import json
import os
import re
import sys


TARGET_REL = "optuna/samplers/_cmaes.py"
TARGET_QUALNAME = "optuna.samplers._cmaes.CmaEsSampler._init_optimizer"
LISTCOMP_QUALNAME = TARGET_QUALNAME + ".<locals>.<listcomp>"
TEST_FILE = "optuna_qa/cmaes_init_optimizer_s4_dataflow/files/testcase.py"
TEST_CLASS = "TestCmaEsInitOptimizerDataFlow"
TEST_METHOD = "test_init_optimizer_many_configs"

TRACKED = [
    "cov",
    "direction",
    "dist",
    "expected_states",
    "i",
    "lower_bounds",
    "mean",
    "n_dimension",
    "sigma0",
    "sign",
    "source_solutions",
    "steps",
    "trans",
    "upper_bounds",
]

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_repo_root():
    here = os.path.abspath(os.path.dirname(__file__))
    for cand in [os.getcwd(), here] + [os.path.abspath(os.path.join(here, *[".."] * k)) for k in range(1, 5)]:
        if os.path.isfile(os.path.join(cand, TARGET_REL)):
            return cand
    fail(f"cannot locate {TARGET_REL}")


def analyze_source(root):
    """Per-line uses/defs of tracked names inside the target function."""
    with open(os.path.join(root, TARGET_REL), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CmaEsSampler":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_init_optimizer":
                    func = item
    if func is None:
        fail("target function not found in source")
    uses, defs = {}, {}
    params = [a.arg for a in func.args.args if a.arg in TRACKED]
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id in TRACKED:
            bucket = uses if isinstance(node.ctx, ast.Load) else defs
            bucket.setdefault(node.lineno, set()).add(node.id)
    return func.lineno, params, uses, defs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        fail("trace log is empty")

    root = find_repo_root()
    def_lineno, params, uses, defs = analyze_source(root)

    stack = []  # reaching-def maps of active target invocations
    pairs = set()
    n_target_events = 0
    n_calls = 0

    for raw in lines:
        m = LINE_RE.match(raw)
        if not m or not m.group("file").endswith(TARGET_REL):
            continue
        func, event, lineno = m.group("func"), m.group("event"), int(m.group("line"))
        if func == TARGET_QUALNAME:
            n_target_events += 1
            if event == "call":
                n_calls += 1
                stack.append({p: def_lineno for p in params})
                continue
            if event == "return":
                if not stack:
                    fail("unbalanced return in trace")
                stack.pop()
                continue
            if event != "line":
                continue
            state = stack[-1]
            for var in sorted(uses.get(lineno, ())):
                if var in state:
                    pairs.add((var, state[var], lineno))
            for var in sorted(defs.get(lineno, ())):
                state[var] = lineno
        elif func == LISTCOMP_QUALNAME:
            if event != "line":
                continue
            if not stack:
                fail("comprehension frame outside target invocation")
            state = stack[-1]
            for var in sorted(uses.get(lineno, ())):
                if var in state:
                    pairs.add((var, state[var], lineno))

    if n_target_events == 0 or n_calls == 0:
        fail("no events for the target function in the trace")
    if not pairs:
        fail("no def-use pairs computed")

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for v, d, u in sorted(pairs)
        ]
    }

    tracked_list = ", ".join(f"`{v}`" for v in TRACKED)
    question = (
        f"Run the pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` (the single test method of "
        f"class `{TEST_CLASS}` in `{TEST_FILE}`). During this test, the method "
        f"`optuna.samplers._cmaes.CmaEsSampler._init_optimizer` (defined in `{TARGET_REL}`) is invoked "
        "several times; an invocation is one call of that method, and the answer aggregates over ALL "
        "invocations during the test (including any that raise). "
        f"Track exactly these local variable names of that method: {tracked_list}. "
        "Report every UNIQUE dynamic def-use pair actually observed at runtime as an object "
        "`{\"variable\": str, \"def_line\": int, \"use_line\": int}` meaning: within one invocation, the "
        "value bound to `variable` by the definition on `def_line` was read on `use_line` before that "
        "variable was redefined in the same invocation. Definitions never carry across invocations. "
        "Definitions: the parameters `trans` and `direction` are defined at the method's `def` line (the "
        "line containing `def _init_optimizer(`) at the start of each invocation; an assignment "
        "statement defines each name in its target list (including tuple-unpacking targets) on the line "
        "where that target name appears; a `for` header defines its loop variables on the header line "
        "each time it binds a new item. A subscript assignment such as `arr[k] = v` is NOT a definition "
        "of `arr`; it is a use (read) of `arr` and of `k`, and attribute/method calls on a variable "
        "(e.g. `obj.append(...)`, `obj.attr`) are uses of it, not definitions. There is no augmented "
        "assignment in this method; if there were, `x += 1` would count as a use of the old definition "
        "followed by a new definition on that line. Uses: a variable is used on a line if its name is "
        "read (loaded) in source on that physical line and that line actually executes during the "
        "invocation; for statements spanning several lines (e.g. multi-line calls with keyword "
        "arguments), the use is attributed to the physical line on which the name token appears, not "
        "the first line of the statement. On a line that both reads and writes a variable (e.g. "
        "`y = f(y)`), the read uses the previous reaching definition and the write then creates a new "
        "definition on that line. The list comprehension inside the method is treated as follows: its "
        "own iteration variable is not tracked (it is not in the list above), but reads of the tracked "
        "enclosing variables inside the comprehension count as uses on the physical line where the name "
        "appears, and only if that part of the comprehension is actually evaluated at least once (e.g. a "
        "condition operand after `and` that is short-circuited for every element, or an element "
        "expression whose filter never passes, contributes no use); such uses resolve to the enclosing "
        "invocation's current reaching definition. All line numbers are absolute, 1-based line numbers "
        f"in `{TARGET_REL}` as it exists in the repository. Each pair is reported once no matter how "
        "many times it was observed. Sort the list by `variable` (ascending string order), then "
        "`def_line` ascending, then `use_line` ascending. Return a JSON object with the single key "
        "`observed_def_use_pairs` whose value is that list; `def_line` and `use_line` are JSON integers "
        "and `variable` is the bare variable name string."
    )

    oracle = {
        "question_kind": "S4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
        },
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={n_calls} target_events={n_target_events} pairs={len(pairs)}")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
