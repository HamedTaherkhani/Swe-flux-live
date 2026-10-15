#!/usr/bin/env python
"""Derive the S2_Loops oracle for procedure_P's BFS while-loop from a trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_SUFFIX = "networkx/algorithms/coloring/equitable_coloring.py"
TARGET_QUALNAME = "networkx.algorithms.coloring.equitable_coloring.procedure_P"
LOOP_HEADER = 156
BODY_FIRST = 157
VARIABLE = "pop"
TARGET_INVOCATION = 9
TARGET_ITERATION = 13

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?| exc=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/equitable_coloring_procedure_p_s2_loops/files/testcase.py::"
    "TestEquitableColoringRegular::test_tight_equitable_coloring_of_random_regular_graph` "
    "(test file `networkx_qa/equitable_coloring_procedure_p_s2_loops/files/testcase.py`, "
    "class `TestEquitableColoringRegular`, its single test method). During this test, the "
    "function `networkx.algorithms.coloring.equitable_coloring.procedure_P` (file "
    "`networkx/algorithms/coloring/equitable_coloring.py`) is invoked several times. "
    "An invocation is one call of `procedure_P` during the test run, counted 1-based in "
    "chronological order of the calls (a recursive call made by `procedure_P` itself, if any, "
    "also counts as its own invocation, numbered by when it starts). "
    f"Look at the `while` loop whose header is at line {LOOP_HEADER} "
    "(`while idx < len(reachable):`, the BFS over colors that builds `A_cal`). "
    f"Iterations of this loop are counted 1-based per invocation: iteration N is the Nth time "
    f"the loop body's first line (line {BODY_FIRST}, `pop = reachable[idx]`) executes within "
    "that invocation. "
    f"In invocation number {TARGET_INVOCATION}, what is the value of the local variable "
    f"`{VARIABLE}` immediately after line {BODY_FIRST} executes in iteration "
    f"{TARGET_ITERATION} of this loop? "
    'Answer with JSON of the form {"nth_iteration": <int>, "value": <int>, "variable": <str>}, '
    'where "nth_iteration" is the iteration number asked about, "variable" is the bare local '
    'variable name (e.g. "idx"), and "value" is the variable\'s value as a plain JSON integer '
    "(not a string, not a repr)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_SUFFIX):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        events.append(
            (int(m.group("lineno")), m.group("event"), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("no events for target function in trace")

    # Reconstruct frames from call/return nesting; locals are logged as diffs.
    stack = []  # list of dicts: {"inv", "locals", "iter", "pending"}
    invocations = 0
    answer_value = None
    for lineno, event, loc in events:
        if event == "call":
            invocations += 1
            stack.append({"inv": invocations, "locals": dict(loc), "iter": 0, "pending": False})
            continue
        if not stack:
            fail("event outside of any traced frame")
        frame = stack[-1]
        frame["locals"].update(loc)
        if event == "return":
            stack.pop()
            continue
        if event != "line":
            continue
        if frame["pending"]:
            # Locals at this event reflect the state after line BODY_FIRST ran.
            answer_value = ast.literal_eval(frame["locals"][VARIABLE])
            frame["pending"] = False
        if lineno == BODY_FIRST:
            frame["iter"] += 1
            if frame["inv"] == TARGET_INVOCATION and frame["iter"] == TARGET_ITERATION:
                frame["pending"] = True

    if invocations < TARGET_INVOCATION:
        fail(f"only {invocations} invocations traced")
    if answer_value is None:
        fail("target iteration not reached")
    if not isinstance(answer_value, int):
        fail(f"unexpected value type: {answer_value!r}")

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"nth_iteration": "int", "value": "int", "variable": "str"},
        "oracle_answer": {
            "nth_iteration": TARGET_ITERATION,
            "value": answer_value,
            "variable": VARIABLE,
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(f"invocations={invocations}")


if __name__ == "__main__":
    main()
