#!/usr/bin/env python
"""Derive the M1_IntraProceduralCFG oracle (per-line execution counts) for
_extrema_bounding from a trace log."""

import argparse
import json
import re
import sys
from collections import Counter

TARGET_SUFFIX = "networkx/algorithms/distance_measures.py"
TARGET_QUALNAME = "networkx.algorithms.distance_measures._extrema_bounding"
FIRST_LINE = 99
LAST_LINE = 244

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
)

TEST_FILE = "networkx_qa/distance_measures_extrema_bounding_m1_cfg/files/testcase.py"
TEST_CLASS = "TestBoundedDistanceMetrics"

QUESTION = (
    f"Run the pytest test class `{TEST_FILE}::{TEST_CLASS}` (test file `{TEST_FILE}`, "
    f"class `{TEST_CLASS}`). The answer aggregates over ALL test methods of this class "
    "(every `test_*` method, each identified by its pytest id "
    f"`{TEST_FILE}::{TEST_CLASS}::<method name>`), run once each under CPython 3.12. "
    "Consider the function `networkx.algorithms.distance_measures._extrema_bounding` "
    "defined in `networkx/algorithms/distance_measures.py` (its `def` line is line 23). "
    "The test never calls it directly; it is reached through the library's public API. "
    "An invocation is one call of this function during the test run. "
    "For every physical line number L from 99 through 244 inclusive (absolute, 1-based "
    "line numbers in that file as it exists in the repository), report how many times "
    "line L was executed in total, summed over all invocations in all test methods. "
    "\"Executed\" is defined exactly as CPython 3.12's `sys.settrace` reports it: count the "
    "`'line'` trace events whose frame is a frame of `_extrema_bounding` itself (frame "
    "code object qualname exactly `_extrema_bounding`) and whose `f_lineno` is L. "
    "Consequences of this definition: `'call'`, `'return'` and `'exception'` events are NOT "
    "counted; the `def` line, decorators and docstring are outside the range; a loop header "
    "line (`for`/`while`) gets an event each time it is evaluated, including the final "
    "evaluation that exits the loop; a statement or condition spanning several physical "
    "lines produces events on whichever of its physical lines CPython reports (e.g. each "
    "separately evaluated sub-condition of a multi-line `if (...)` may fire on its own "
    "line), and these are counted on that reported line; list/set comprehensions are "
    "inlined into the function's frame in 3.12 (PEP 709), so their line events count, "
    "possibly several times per element; but generator expressions run in their own frame "
    "(qualname `_extrema_bounding.<locals>.<genexpr>`) and their line events are NOT counted "
    "(only the event of the enclosing statement in `_extrema_bounding`'s frame counts). "
    "Blank lines, comment-only lines, and any line that never produced such an event "
    "(including unreached code and continuation lines that never fire) MUST still be "
    "listed, with count 0. "
    'Answer with JSON of the form {"line_execution_counts": [{"count": <int>, "line": <int>}, ...]} '
    "containing exactly one object per line number in 99..244 (146 entries, no duplicates), "
    "sorted by `line` ascending; both values are plain JSON integers (e.g. "
    '{"count": 3, "line": 7}).'
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

    counts = Counter()
    calls = 0
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_SUFFIX):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "line":
            counts[int(m.group("lineno"))] += 1
    if calls == 0 or not counts:
        fail("no call/line events for the target function in the trace")
    outside = sorted(ln for ln in counts if not FIRST_LINE <= ln <= LAST_LINE)
    if outside:
        fail(f"line events outside the scoped range: {outside}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(ln, 0), "line": ln}
            for ln in range(FIRST_LINE, LAST_LINE + 1)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={calls} line_events={sum(counts.values())} "
          f"distinct_lines={len(counts)}")


if __name__ == "__main__":
    main()
