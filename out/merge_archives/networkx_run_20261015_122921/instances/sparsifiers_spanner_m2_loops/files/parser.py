"""Derive the M2_Loops oracle for sparsifiers.spanner from the trace log."""

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.algorithms.sparsifiers.spanner"
TARGET_FILE = "networkx/algorithms/sparsifiers.py"
LOOP_HEADER_LINE = 139
BODY_FIRST_LINE = 140

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) "
)

QUESTION = (
    "Consider the pytest test class `TestSpannerLoops` in the file "
    "`networkx_qa/sparsifiers_spanner_m2_loops/files/testcase.py`. The answer "
    "aggregates over ALL test methods of that class (every `test_*` method, i.e. "
    "pytest ids `networkx_qa/sparsifiers_spanner_m2_loops/files/testcase.py::"
    "TestSpannerLoops::<method>`), run together in one pytest session. "
    "Target function: `networkx.algorithms.sparsifiers.spanner`, defined in "
    "`networkx/algorithms/sparsifiers.py`. An invocation is one call of this "
    "function's own frame during the test run (1-based, chronological order); "
    "invocations that raise before reaching any loop still count as invocations "
    "but contribute nothing. "
    f"Focus on the inner `for neighbor in residual_graph.adj[v]:` loop whose header "
    f"is on line {LOOP_HEADER_LINE} of that file (the edge-removal loop inside the "
    "`else:` branch for a node that has a neighboring sampled center; it is nested "
    "in the `for v in residual_graph.nodes:` loop on line 98, which is itself nested "
    "in the `while i < k - 1:` loop on line 87). Do NOT confuse it with the similar "
    "loop on line 117. One iteration of the line-"
    f"{LOOP_HEADER_LINE} loop = one execution of its body's first line, line "
    f"{BODY_FIRST_LINE} (`nbr_cluster = clustering[neighbor]`), counted 1-based. "
    "Every execution counts, including executions during passes of the `while` loop "
    "that are later discarded by the `continue` on line 152 (size-limit retry). "
    "Report the total number of iterations of the line-"
    f"{LOOP_HEADER_LINE} loop summed over every entry of that loop, over every "
    "invocation of `spanner`, over all test methods of the class. "
    "Answer as a JSON object with exactly one key, `total_iterations`, whose value "
    "is a JSON integer (e.g. {\"total_iterations\": 3}), not a string."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    src_lines = Path(TARGET_FILE).read_text(encoding="utf-8").splitlines()
    if src_lines[LOOP_HEADER_LINE - 1].strip() != "for neighbor in residual_graph.adj[v]:":
        fail("loop header line does not match expected source")
    if src_lines[BODY_FIRST_LINE - 1].strip() != "nbr_cluster = clustering[neighbor]":
        fail("loop body first line does not match expected source")

    calls = 0
    events = 0
    iterations = 0
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        events += 1
        ev = m.group("event")
        line = int(m.group("line"))
        if ev == "call":
            calls += 1
        elif ev == "line" and line == BODY_FIRST_LINE:
            iterations += 1

    if events == 0 or calls == 0:
        fail(f"no events for {TARGET_QUALNAME} in trace")
    if iterations == 0:
        fail("target loop never iterated; scenario is broken")

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": iterations},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={calls} target_events={events}")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
