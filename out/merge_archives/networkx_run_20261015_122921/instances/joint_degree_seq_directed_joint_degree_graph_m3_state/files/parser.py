#!/usr/bin/env python
"""Collect the distinct repr values of `chords` inside directed_joint_degree_graph."""

import argparse
import ast
import json
import os
import re
import sys

REL_FILE = "networkx/generators/joint_degree_seq.py"
FUNC = "networkx.generators.joint_degree_seq.directed_joint_degree_graph"
VAR = "chords"
TEST_FILE = (
    "networkx_qa/joint_degree_seq_directed_joint_degree_graph_m3_state/files/testcase.py"
)
TEST_CLASS = "TestDirectedJointDegreeGraph"
TRUNC_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?| exc=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    f"Run the whole pytest class `{TEST_FILE}::{TEST_CLASS}` (test file `{TEST_FILE}`, class "
    f"`{TEST_CLASS}`) from the repository root with the repository's Python (CPython 3.12). The answer "
    "aggregates over ALL test methods of the class (all twelve `test_...` methods, run in their "
    "pytest/definition order; order does not affect the answer since values are deduplicated and "
    "sorted). These methods call the function `directed_joint_degree_graph` defined in "
    f"`{REL_FILE}` (fully qualified `{FUNC}`) directly; consider every invocation of it during the "
    "run (invocation = one call of the function, including invocations that raise).\n\n"
    "Track the local variable `chords` in the frame of `directed_joint_degree_graph` itself (not the "
    "parameter of the same name inside the helper functions `_directed_neighbor_switch` / "
    "`_directed_neighbor_switch_rev`, although in-place mutations those helpers make to the shared "
    "set object ARE visible in the caller's `chords` once they return). Observation points: "
    "immediately before each statement (each executed line) of `directed_joint_degree_graph`'s own frame "
    "executes, and at the moment the function returns. At each observation point where `chords` is "
    "bound, take `repr(chords)` - the plain CPython repr of the set object exactly as Python prints it, "
    "with its elements in the set's actual iteration order at that moment (NOT re-sorted), e.g. a "
    "set holding tuples prints like `{(4, 2), (1, 9)}` and an empty set prints as `set()`. "
    "Observation points where `chords` is not yet bound contribute nothing. Intermediate states that "
    "exist only while a helper function is executing (e.g. an element added and then discarded within "
    "one helper call) are not observed.\n\n"
    "Answer format: a JSON object `{\"unique_values\": [...]}` whose list contains each distinct repr "
    "string exactly once (deduplicated across all observation points and all invocations), sorted "
    "ascending by plain Python string comparison (code-point order, i.e. `sorted()` of the strings)."
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    values = set()
    state = None  # locals of the current invocation (no recursion in target)
    n_events = 0
    n_calls = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != FUNC or not m.group("file").endswith(REL_FILE):
                continue
            n_events += 1
            event = m.group("event")
            loc = ast.literal_eval(m.group("locals"))
            if event == "call":
                n_calls += 1
                state = dict(loc)
                continue
            if state is None:
                die("event before call")
            if event == "return":
                state = dict(loc)
            else:
                state.update(loc)
            if event in ("line", "return") and VAR in state:
                val = state[VAR]
                if len(val) > TRUNC_LIMIT:
                    die("chords repr truncated by tracer")
                values.add(val)
            if event == "return":
                state = None

    if n_events == 0 or n_calls == 0:
        die(f"no events for {FUNC} in trace")
    if not values:
        die("no observed values of chords")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
    print(f"invocations={n_calls} events={n_events} unique_values={len(values)}")


if __name__ == "__main__":
    main()
