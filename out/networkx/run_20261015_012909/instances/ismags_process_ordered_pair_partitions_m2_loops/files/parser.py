#!/usr/bin/env python
"""Derive the M2_Loops oracle for ISMAGS._process_ordered_pair_partitions.

Per invocation, count executions of line 1497 (first body line of the inner
``for node2 in node2_iter`` loop at line 1496, nested in the ``while queue``
loop at line 1493). Report max and min over all invocations in the test class.
"""

import argparse
import json
import re
import sys

TARGET_SUFFIX = "networkx/algorithms/isomorphism/ismags.py"
TARGET_QUALNAME = (
    "networkx.algorithms.isomorphism.ismags.ISMAGS._process_ordered_pair_partitions"
)
WHILE_HEADER = 1493
FOR_HEADER = 1496
BODY_FIRST = 1497
TEST_FILE = "networkx_qa/ismags_process_ordered_pair_partitions_m2_loops/files/testcase.py"
TEST_CLASS = "TestIsmagsSymmetricPatterns"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    f"Run all test methods of the class `{TEST_CLASS}` in the pytest test file "
    f"`{TEST_FILE}` (i.e. the pytest node `{TEST_FILE}::{TEST_CLASS}`; the answer "
    "aggregates over ALL test methods of that class together, there are no other "
    "tests involved). During this run, the method "
    "`networkx.algorithms.isomorphism.ismags.ISMAGS._process_ordered_pair_partitions` "
    f"(file `{TARGET_SUFFIX}`) is invoked one or more times; it is never called "
    "directly by the tests but is reached through ISMAGS's public search methods. "
    "An invocation is one call of this method (one execution of its frame from call "
    "to return), counted 1-based in chronological order over the whole run. "
    f"Inside it there is a `while queue:` loop whose header is at line {WHILE_HEADER}, "
    f"and nested inside that a `for node2 in node2_iter:` loop whose header is at line "
    f"{FOR_HEADER}. Line numbers are absolute, 1-based, in that file as it exists in "
    "the repository. For each invocation, define its inner-loop iteration count as the "
    f"total number of times line {BODY_FIRST} (the inner loop body's first line, "
    "`if node != node2 and orbit_id[node] == orbit_id[node2]:`) executes in that "
    "invocation's own frame, summed over all iterations of the enclosing `while` loop "
    "(every execution counts, including ones that then hit `continue` or `break`; a "
    "`node2_iter` iterator that is resumed in a later `while` iteration keeps "
    "contributing to the same invocation's count). Executions inside nested function "
    "frames (e.g. `_load_next_queue_entry`, comprehensions/generator expressions) or "
    "inside other methods called from it do not count. An invocation that returns "
    f"before reaching the `while` loop has a count of 0 and is still included. "
    "What are the maximum and the minimum of this per-invocation count over all "
    "invocations during the run? Answer with JSON of the form "
    '{"max_iterations": <int>, "min_iterations": <int>}, both values plain JSON '
    "integers."
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
            lines = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not lines:
        fail("trace log is empty")

    counts = []
    current = None
    events = 0
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_SUFFIX):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        events += 1
        ev = m.group("event")
        lineno = int(m.group("lineno"))
        if ev == "call":
            if current is not None:
                fail("nested/overlapping invocation of target; unexpected")
            current = 0
        elif ev == "line":
            if current is None:
                fail(f"line event outside of an invocation: {raw}")
            if lineno == BODY_FIRST:
                current += 1
        elif ev == "return":
            if current is None:
                fail("return without call")
            counts.append(current)
            current = None
    if events == 0:
        fail("no events for target function in trace")
    if current is not None:
        fail("trace ended inside an invocation")
    if not counts:
        fail("no completed invocations of target")

    print(f"invocations={len(counts)} per_invocation_counts={counts}")
    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {
            "max_iterations": max(counts),
            "min_iterations": min(counts),
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
