#!/usr/bin/env python
"""Derive the M3_ProgramState oracle (distinct repr values of ``dq_vw``) for
_greedy_modularity_communities_generator from a trace log."""

import argparse
import json
import re
import sys

TARGET_SUFFIX = "networkx/algorithms/community/modularity_max.py"
TARGET_QUALNAME = (
    "networkx.algorithms.community.modularity_max._greedy_modularity_communities_generator"
)
VARIABLE = "dq_vw"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
)
VAR_RE = re.compile(r"'" + VARIABLE + r"': '([^']*)'")

TEST_FILE = (
    "networkx_qa/modularity_max_greedy_modularity_communities_generator_m3_state/"
    "files/testcase.py"
)
TEST_CLASS = "TestGreedyModularityScenarios"

QUESTION = (
    f"Run the pytest test class `{TEST_FILE}::{TEST_CLASS}` (test file `{TEST_FILE}`, "
    f"class `{TEST_CLASS}`). The answer aggregates over ALL test methods of this class "
    "(every `test_*` method, each identified by its pytest id "
    f"`{TEST_FILE}::{TEST_CLASS}::<method name>`), run once each under CPython 3.12. "
    "Consider the generator function "
    "`networkx.algorithms.community.modularity_max._greedy_modularity_communities_generator` "
    "defined in `networkx/algorithms/community/modularity_max.py` (its `def` line is line 15). "
    "The test never calls it directly; it is reached through the public API "
    "`greedy_modularity_communities`, which consumes the generator only as far as its "
    "stopping rules (`cutoff`, `best_n`, negative `dq`) require. "
    "An invocation is one generator object created by that caller (one per call of "
    "`greedy_modularity_communities` that gets past its early-return checks); generator "
    "resumptions are part of the same invocation. "
    "Across all invocations in all test methods, collect every value that is bound to the "
    "local variable `dq_vw` inside the generator's frame, i.e. every value assigned by the "
    "statements on lines 154, 156 and 158 (`dq_vw = ...`, absolute 1-based line numbers in "
    "that file) that actually execute while the generator is being driven by the test. "
    "Represent each value by Python `repr()` of the float (CPython's shortest round-trip "
    "repr, e.g. a value of one tenth is written `'0.1'`, a negative value keeps its leading "
    "`-`, never rounded or reformatted). Remove duplicates: two values are the same entry "
    "iff their repr strings are identical. "
    'Answer with JSON of the form {"unique_values": [<str>, ...]} where each element is '
    "such a repr string (a JSON string), sorted ascending by numeric value (`float(s)`), "
    "with ties (equal floats having different reprs, e.g. `-0.0` and `0.0`) broken by "
    "ordinary string comparison of the repr."
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

    events = 0
    values = set()
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_SUFFIX):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        events += 1
        idx = line.rfind(" locals={")
        if idx < 0:
            continue
        for val in VAR_RE.findall(line[idx:]):
            if val.endswith("..."):
                fail(f"truncated repr for {VARIABLE}: {val}")
            float(val)  # must be a float repr
            values.add(val)
    if events == 0:
        fail("no events for the target function in the trace")
    if not values:
        fail(f"no values observed for {VARIABLE}")

    answer = {"unique_values": sorted(values, key=lambda s: (float(s), s))}
    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"target_events={events} unique_values={len(values)}")


if __name__ == "__main__":
    main()
