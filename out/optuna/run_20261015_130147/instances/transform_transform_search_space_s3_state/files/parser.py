#!/usr/bin/env python
"""Trace -> oracle.json for transform_transform_search_space_s3_state (S3_ProgramState)."""

import argparse
import ast
import json
import os
import re
import sys


TARGET_REL = "optuna/_transform.py"
TARGET_QUALNAME = "optuna._transform._transform_search_space"
TEST_FILE = "optuna_qa/transform_transform_search_space_s3_state/files/testcase.py"
TEST_CLASS = "TestTransformSearchSpaceState"
TEST_METHOD = "test_transform_mixed_search_space"
VARIABLE = "bds"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)? locals=(?P<locals>\{.*\})$"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_repo_root():
    here = os.path.abspath(os.path.dirname(__file__))
    for cand in [os.getcwd(), here] + [
        os.path.abspath(os.path.join(here, *[".."] * k)) for k in range(1, 5)
    ]:
        if os.path.isfile(os.path.join(cand, TARGET_REL)):
            return cand
    fail(f"cannot locate {TARGET_REL}")


def assignment_lines(root):
    """Line numbers of statements in the target that assign VARIABLE, and the line that uses it."""
    with open(os.path.join(root, TARGET_REL), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_transform_search_space":
            func = node
    if func is None:
        fail("target function not found")
    defs = sorted(
        n.lineno
        for n in ast.walk(func)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == VARIABLE for t in n.targets)
    )
    if not defs:
        fail("no assignments to tracked variable found")
    return func, defs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        fail("trace log empty")

    root = find_repo_root()
    func, def_lines = assignment_lines(root)

    events = []
    for ln in raw:
        m = LINE_RE.match(ln)
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        events.append(
            (int(m.group("line")), m.group("event"), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("zero events for target function in trace")

    calls = [i for i, e in enumerate(events) if e[1] == "call"]
    if len(calls) != 1:
        fail(f"expected exactly one invocation of target, got {len(calls)}")

    # Walk the single invocation, rebuilding the full locals state from diffs.
    # The locals shown at a line event are the state *before* that line runs, so the
    # value assigned by a statement starting on line L is visible at the next line event.
    state = {}
    history = []
    pending = False
    n_line_events = 0
    for lineno, event, loc in events[calls[0]:]:
        if event == "return":
            state = dict(loc)
        else:
            state.update(loc)
        if pending:
            if VARIABLE not in state:
                fail("tracked variable missing after its assignment")
            history.append(state[VARIABLE])
            pending = False
        if event == "line":
            n_line_events += 1
            if lineno in def_lines:
                pending = True
        if event in ("return", "exception"):
            break
    if pending:
        fail("assignment not followed by another event")
    if len(history) < 8:
        fail(f"history too short: {len(history)}")

    oracle_answer = {
        "value_history": [{"step": i + 1, "value": v} for i, v in enumerate(history)]
    }
    template_answer = {"value_history": [{"step": "int", "value": "str"}]}

    question = (
        f"Consider the pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` "
        f"(test class `{TEST_CLASS}`, its single test method `{TEST_METHOD}`). "
        f"During this test the function `{TARGET_QUALNAME}` (defined in `{TARGET_REL}`, "
        f"lines {func.lineno}-{func.end_lineno}) is invoked exactly once. "
        f"Report the complete ordered history of values bound to the local variable "
        f"`{VARIABLE}` during that invocation. A new history entry is produced every time "
        f"an assignment statement whose target is `{VARIABLE}` finishes executing "
        f"(the multi-line `{VARIABLE} = (...)` statements in the FloatDistribution and "
        f"IntDistribution branches, which start on lines "
        f"{', '.join(str(x) for x in def_lines)}). Every executed assignment counts as its "
        f"own entry, even if the new value equals the previous one (no deduplication); "
        f"entries are in chronological execution order. Iterations that handle a "
        f"CategoricalDistribution do not assign `{VARIABLE}` and therefore produce no entry. "
        f"Answer as JSON of the form "
        f'{{"value_history": [{{"step": <int>, "value": <str>}}, ...]}} where `step` is the '
        f"1-based position of the assignment in chronological order (1, 2, 3, ...) and "
        f"`value` is the Python `repr()` of the value of `{VARIABLE}` immediately after that "
        f"assignment completes, i.e. the repr of the whole tuple exactly as Python prints it "
        f"(for example a tuple of two floats looks like `(-1.25, 3.0)`, with full shortest "
        f"round-trip float digits as produced by `repr(float)`, a space after the comma, and "
        f"no numpy wrappers if the elements are plain Python floats)."
    )

    out = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"line events in target: {n_line_events}; history length: {len(history)}")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
