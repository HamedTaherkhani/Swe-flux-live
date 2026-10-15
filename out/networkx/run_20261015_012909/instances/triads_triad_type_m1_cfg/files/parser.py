#!/usr/bin/env python
"""Build oracle.json (per-line execution counts of triad_type) from the trace log."""

import argparse
import json
import re
import sys
from collections import Counter

TARGET_FILE = "networkx/algorithms/triads.py"
TARGET_QUALNAME = "networkx.algorithms.triads.triad_type"
SCOPE_START = 456
SCOPE_END = 500

EVENT_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Consider the pytest test class `TestTriadsByTypeScenarios` in the file \
`networkx_qa/triads_triad_type_m1_cfg/files/testcase.py`, run in full with pytest \
(all of its test methods: pytest ids \
`networkx_qa/triads_triad_type_m1_cfg/files/testcase.py::TestTriadsByTypeScenarios::<method>`). \
The test methods never call the target directly; they call public NetworkX APIs which reach it.

Target function: `{TARGET_QUALNAME}` (the function `triad_type` defined at \
`{TARGET_FILE}` line 407, below its decorators).

For every physical source line in the inclusive range {SCOPE_START}..{SCOPE_END} of \
`{TARGET_FILE}` (i.e. the whole body of `triad_type` after its docstring; the `def` line, \
the decorator lines and the docstring are NOT in scope), report how many times that line \
executed, totalled over ALL invocations of `triad_type` in ALL test methods of the class \
(including invocations whose test expects an exception).

Definitions:
- "Line executed" = a CPython line event (as observed by a `sys.settrace` line-level tracer \
on frames of `triad_type` itself, Python 3.12) reporting that line number inside a \
`triad_type` frame. Lines of other functions (callees such as `is_triad`, decorators/wrappers, \
helpers) never count toward this function's lines.
- A `for` statement's header line fires once each time the loop fetches its next item \
(i.e. once per iteration started, plus once more if the iterator is exhausted normally); \
`if`/`elif` lines fire each time their condition is evaluated. All statements in scope are \
single physical lines.
- Lines in scope that are comments-only, blank, or never executed MUST still appear, with \
`count` 0. Every line number from {SCOPE_START} to {SCOPE_END} inclusive appears exactly once.

Output format: a JSON object `{{"line_execution_counts": [{{"count": <int>, "line": <int>}}, ...]}}` \
where `line` is the absolute 1-based line number in `{TARGET_FILE}` and `count` is a \
non-negative integer; the list is sorted by `line` ascending (no duplicates). \
Example of one element (not from the answer): {{"count": 3, "line": 1234}}.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log not found: {args.trace_log}")
    if not raw:
        sys.exit(f"ERROR: trace log is empty: {args.trace_log}")

    counts = Counter()
    n_calls = 0
    n_events = 0
    for row in raw:
        m = EVENT_RE.match(row)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE) or m.group("func") != TARGET_QUALNAME:
            continue
        n_events += 1
        if m.group("event") == "call":
            n_calls += 1
        elif m.group("event") == "line":
            counts[int(m.group("line"))] += 1

    if n_events == 0 or n_calls == 0 or not counts:
        sys.exit("ERROR: no trace events for target function triad_type")
    outside = sorted(k for k in counts if not SCOPE_START <= k <= SCOPE_END)
    if outside:
        sys.exit(f"ERROR: line events outside expected scope: {outside}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(ln, 0), "line": ln}
            for ln in range(SCOPE_START, SCOPE_END + 1)
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
    print(f"calls={n_calls} line_events={sum(counts.values())} distinct_lines={len(counts)}")
    print(json.dumps(answer))


if __name__ == "__main__":
    main()
