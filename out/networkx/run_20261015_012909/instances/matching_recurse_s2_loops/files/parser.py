#!/usr/bin/env python
"""Parse the trace log into the oracle for matching_recurse_s2_loops."""

import argparse
import json
import re
import sys

TARGET_FILE = "networkx/algorithms/matching.py"
TARGET_QUAL = (
    "networkx.algorithms.matching.max_weight_matching.<locals>"
    ".expandBlossom.<locals>._recurse"
)
LOOP_HEADER = 736
BODY_FIRST_LINE = 740

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/matching_recurse_s2_loops/files/testcase.py::"
    "TestMaxWeightMatchingBlossoms::test_random_dense_graph` (file "
    "`networkx_qa/matching_recurse_s2_loops/files/testcase.py`, class "
    "`TestMaxWeightMatchingBlossoms`, single test method "
    "`test_random_dense_graph`). It calls `networkx.max_weight_matching` on a "
    "seeded random weighted graph. During that call, the nested generator "
    "function `networkx.algorithms.matching.max_weight_matching.<locals>."
    "expandBlossom.<locals>._recurse` (defined in "
    "`networkx/algorithms/matching.py`, lines 676-767) is created and driven "
    "by `expandBlossom`'s trampoline possibly many times, for different "
    "blossoms and with different `endstage` values.\n\n"
    f"Focus on the `while b.childs[j] != entrychild:` loop whose header is at "
    f"line {LOOP_HEADER} of `networkx/algorithms/matching.py` (line numbers "
    "are absolute, 1-based, as the file exists in the repository). Define one "
    "iteration of this loop as one execution of the loop body's first "
    "statement, `bv = b.childs[j]` (the line directly below the header); iterations that end early "
    "via `continue` still count, and evaluations of the loop condition that "
    "do not enter the body do not count.\n\n"
    "What is the TOTAL number of iterations of this loop, summed over every "
    "`_recurse` generator instance (every blossom expansion, nested or "
    "top-level, mid-stage or end-of-stage) executed during the whole test "
    "method? Instances in which the loop is never reached contribute 0.\n\n"
    'Answer as JSON of the form {"loop_iteration_count": <int>}, where the '
    "value is a plain JSON integer (not a string)."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log not found: {args.trace_log}")
    if not lines:
        sys.exit(f"ERROR: trace log is empty: {args.trace_log}")

    target_events = 0
    count = 0
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        if m.group("func") != TARGET_QUAL:
            continue
        target_events += 1
        if m.group("event") == "line" and int(m.group("lineno")) == BODY_FIRST_LINE:
            count += 1

    if target_events == 0:
        sys.exit("ERROR: no trace events for the target function")

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"]))
    print(f"target events: {target_events}")


if __name__ == "__main__":
    main()
