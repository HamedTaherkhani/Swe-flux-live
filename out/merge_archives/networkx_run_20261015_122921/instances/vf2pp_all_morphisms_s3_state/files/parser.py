#!/usr/bin/env python
"""Derive the S3_ProgramState oracle for vf2pp_all_morphisms_s3_state from a trace log."""

import argparse
import ast
import json
import sys

TARGET_FILE = "networkx/algorithms/isomorphism/vf2pp.py"
TARGET_FUNC = "networkx.algorithms.isomorphism.vf2pp._all_morphisms"
OBS_LINE = 543
OBS_OCCURRENCE = 87
VARIABLES = sorted(
    [
        "cand",
        "candidate",
        "current_node",
        "mapping",
        "node",
        "node_number",
        "node_order",
        "rev_map",
    ]
)
TRACE_REPR_LIMIT = 500

QUESTION = f"""\
Test: networkx_qa/vf2pp_all_morphisms_s3_state/files/testcase.py::TestVF2ppExhaustiveSearch::test_cubic_pair_not_isomorphic (test class `TestVF2ppExhaustiveSearch`, single test method `test_cubic_pair_not_isomorphic`).

Target function: `networkx.algorithms.isomorphism.vf2pp._all_morphisms` in file `networkx/algorithms/isomorphism/vf2pp.py` (a generator function). The test reaches it only indirectly, through the public API.

Observation point: line {OBS_LINE} of `networkx/algorithms/isomorphism/vf2pp.py` (absolute, 1-based line number in the file as it exists in the repository; it is the `restore_Tinout(node, cand, graph_info, state_info)` statement in the backtracking branch of the main `while stack:` loop). Count every execution of that line inside `_all_morphisms` over the whole test run, 1-based, in chronological order (during this test the function is invoked exactly once). Consider the moment immediately after line {OBS_LINE} has finished executing for the {OBS_OCCURRENCE}-th time (occurrence number {OBS_OCCURRENCE} in the 1-based count), i.e. after the `restore_Tinout` call has returned and before the following `continue` statement runs.

At that moment, report the values of these local variables of the `_all_morphisms` frame: {", ".join("`" + v + "`" for v in VARIABLES)}.

Answer format: a JSON object {{"observed_state": [...]}} whose list contains exactly one entry per variable listed above, each entry being {{"variable": <variable name as a string>, "value": <string>}}. Entries are sorted by variable name in ascending lexicographic (code-point) order. Each "value" is the Python `repr()` of the variable's current value at the observation point, as a string. For containers this is the `repr` of the whole container exactly as Python prints it (dicts in their current insertion order, lists in their element order, strings inside them keep their single quotes, e.g. a dict would look like {{2: 'x', 7: 'y'}} and a list like [5, 'q']). Python spellings such as `None`/`True` would appear inside the strings, never JSON `null`/`true`. No variable is omitted and no extra variables are added.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_event(raw):
    parts = raw.split(" ", 4)
    if len(parts) < 5:
        return None
    loc, func, rest = parts[2], parts[3], parts[4]
    if not rest.startswith("event="):
        return None
    event = rest[len("event=") :].split(" ", 1)[0]
    file_path, _, lineno = loc.rpartition(":")
    idx = rest.rfind(" locals=")
    if idx < 0:
        return None
    locals_dict = ast.literal_eval(rest[idx + len(" locals=") :])
    return file_path, int(lineno), func, event, locals_dict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not lines:
        fail("trace log is empty")

    events = []
    for raw in lines:
        if "[TRACE]" in raw:
            continue
        ev = parse_event(raw)
        if ev is None:
            continue
        file_path, lineno, func, event, loc = ev
        if not file_path.endswith(TARGET_FILE) or func != TARGET_FUNC:
            continue
        events.append((lineno, event, loc))
    if not events:
        fail("no trace events for the target function")

    calls = sum(1 for e in events if e[1] == "call")
    if calls != 1:
        fail(f"expected exactly one call event of the target, got {calls}")

    state = {}
    seen = 0
    pending = False
    observed = None
    for lineno, event, loc in events:
        if event == "call":
            state = {}
        state.update(loc)
        if pending:
            if event != "line" or lineno != OBS_LINE + 1:
                fail(f"unexpected event after observation line: {lineno} {event}")
            observed = dict(state)
            break
        if event == "line" and lineno == OBS_LINE:
            seen += 1
            if seen == OBS_OCCURRENCE:
                pending = True
    if observed is None:
        fail(f"line {OBS_LINE} executed only {seen} times; need {OBS_OCCURRENCE}")

    answer = []
    for var in VARIABLES:
        if var not in observed:
            fail(f"variable {var} not present at observation point")
        val = observed[var]
        if len(val) > TRACE_REPR_LIMIT and val.endswith("..."):
            fail(f"repr of {var} was truncated by the tracer")
        answer.append({"value": val, "variable": var})

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": answer},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
