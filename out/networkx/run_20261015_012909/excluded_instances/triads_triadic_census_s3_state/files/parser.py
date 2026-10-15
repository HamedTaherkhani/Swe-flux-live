#!/usr/bin/env python
"""Harvest S3_ProgramState oracle for networkx.algorithms.triads.triadic_census."""

import argparse
import ast
import json
import re
import sys

TARGET_FUNC = "networkx.algorithms.triads.triadic_census"
TARGET_FILE_SUFFIX = "networkx/algorithms/triads.py"
OBS_LINE = 269
OBS_K = 6
INVOCATION = 1
VARIABLES = [
    "census",
    "dbl_edges_outside",
    "dbl_unbrs_bdy",
    "dbl_unbrs_out",
    "sgl_edges_outside",
    "sgl_unbrs_bdy",
    "sgl_unbrs_out",
    "u",
    "v",
]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) "
    r"(?:exc=.*? |retval=.*? )?locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/triads_triadic_census_s3_state/files/testcase.py::"
    "TestTriadicCensusSubset::test_census_on_node_subset` (test file "
    "`networkx_qa/triads_triadic_census_s3_state/files/testcase.py`, class "
    "`TestTriadicCensusSubset`, single test method `test_census_on_node_subset`). "
    "During this test the function `networkx.algorithms.triads.triadic_census` "
    "(defined in `networkx/algorithms/triads.py`) is invoked more than once; an "
    "invocation is one call of the function body, counted 1-based in "
    "chronological order. Focus ONLY on invocation 1 (the call "
    "`triadic_census(G, nodelist)` with the node subset).\n\n"
    f"Within invocation 1, line {OBS_LINE} of `networkx/algorithms/triads.py` "
    "(the statement `census[\"102\"] += dbl_edges_outside - (dbl_unbrs_out + "
    "dbl_unbrs_bdy // 2)` inside the `if Nnot:` block at the end of the main "
    "`for v in nodeset:` loop body) executes several times. Line numbers are "
    "absolute and 1-based in the file as it exists in the repository. "
    f"Observe the function's local variables immediately AFTER line {OBS_LINE} "
    f"has finished executing for the {OBS_K}th time in invocation 1 (i.e. "
    "including the effect of that execution of the augmented assignment, and "
    "before any later statement runs).\n\n"
    "Report the value of each of these local variables at that moment: "
    + ", ".join(f"`{v}`" for v in VARIABLES)
    + ". Each value is the Python `repr()` of the variable's current value, "
    "given as a JSON string (for a dict, the `repr` of the whole dict in its "
    "actual insertion order, e.g. `\"{'a': 1, 'b': 2}\"`; integers as e.g. "
    "`\"7\"`). Note that a loop variable such as `u` keeps the value it was "
    "last bound to by the inner `for u in vnbrs:` loop, even if that iteration "
    "hit `continue`.\n\n"
    "Answer format: a JSON object `{\"observed_state\": [...]}` where the list "
    "has exactly one entry per variable listed above, each entry an object "
    "`{\"value\": <repr string>, \"variable\": <variable name string>}`, with "
    "entries sorted by `variable` in ascending (lexicographic) order."
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
    for ln in raw:
        m = LINE_RE.match(ln)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        if not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        events.append(
            (
                int(m.group("line")),
                m.group("event"),
                ast.literal_eval(m.group("locals")),
            )
        )
    if not events:
        fail("no events for target function in trace")

    # Split invocations (no recursion in target): call ... return
    invocations = []
    cur = None
    for ev in events:
        if ev[1] == "call":
            cur = [ev]
            invocations.append(cur)
        elif cur is not None:
            cur.append(ev)
            if ev[1] == "return":
                cur = None
    if len(invocations) < INVOCATION:
        fail(f"only {len(invocations)} invocations found")
    inv = invocations[INVOCATION - 1]

    state = {}
    hits = 0
    observed = None
    pending = False
    for line, event, loc in inv:
        if event == "return":
            state = dict(loc)  # full locals on return
        else:
            state.update(loc)
        if pending:
            # state at the next event == state right after OBS_LINE finished
            observed = dict(state)
            break
        if event == "line" and line == OBS_LINE:
            hits += 1
            if hits == OBS_K:
                pending = True
    if observed is None:
        fail(f"line {OBS_LINE} executed only {hits} times in invocation {INVOCATION}")

    out_state = []
    for var in sorted(VARIABLES):
        if var not in observed:
            fail(f"variable {var} not bound at observation point")
        val = observed[var]
        if val.endswith("...") and len(val) > 500:
            fail(f"value of {var} truncated by tracer")
        out_state.append({"value": val, "variable": var})

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": out_state},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
