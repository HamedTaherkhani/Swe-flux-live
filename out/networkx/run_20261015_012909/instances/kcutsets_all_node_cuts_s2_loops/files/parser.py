"""Derive the S2_Loops oracle for kcutsets.all_node_cuts from the trace log."""

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.algorithms.connectivity.kcutsets.all_node_cuts"
TARGET_FILE = "networkx/algorithms/connectivity/kcutsets.py"
LOOP_HEADER_LINE = 179
BODY_FIRST_LINE = 180

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the single pytest test "
    "`networkx_qa/kcutsets_all_node_cuts_s2_loops/files/testcase.py::"
    "TestAllNodeCutsLoops::test_all_node_cuts_regular_graph` (class "
    "`TestAllNodeCutsLoops`, method `test_all_node_cuts_regular_graph`). "
    "Target function: `networkx.algorithms.connectivity.kcutsets.all_node_cuts`, "
    "defined in `networkx/algorithms/connectivity/kcutsets.py` (a generator). "
    "The test creates exactly one generator object from `all_node_cuts` and "
    "consumes it completely with `list(...)`; treat that whole consumption "
    "(across all suspensions/resumptions at `yield`) as the single invocation "
    "the question is about. "
    f"Focus on the loop `for antichain in nx.antichains(L):` whose header is on "
    f"line {LOOP_HEADER_LINE} of that file (absolute, 1-based line numbers in the "
    "file as it exists in the repository). This loop is nested inside "
    "`if flow_value == k:` (line 151), the `for v in non_adjacent:` loop "
    "(line 139) and the `for x in X:` loop (line 135), so it may be entered "
    "several times. One iteration = one execution of the loop body's first "
    f"line, line {BODY_FIRST_LINE} (`if not antichain:`); every such execution "
    "counts, including iterations that are cut short by any of the `continue` "
    "statements in the body (e.g. for the empty antichain). "
    f"Report the total number of iterations of the line-{LOOP_HEADER_LINE} loop, "
    "summed over every entry of that loop during the whole invocation. "
    "Answer as a JSON object with exactly one key, `loop_iteration_count`, "
    "whose value is a JSON integer (e.g. {\"loop_iteration_count\": 3}), "
    "not a string."
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
    if src_lines[LOOP_HEADER_LINE - 1].strip() != "for antichain in nx.antichains(L):":
        fail("loop header line does not match expected source")
    if src_lines[BODY_FIRST_LINE - 1].strip() != "if not antichain:":
        fail("loop body first line does not match expected source")

    events = 0
    first_calls = 0
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
        line = int(m.group("line"))
        ev = m.group("event")
        # A fresh generator start fires `call` on the def line; resumptions
        # fire `call` on the suspended yield line.
        if ev == "call" and src_lines[line - 1].lstrip().startswith(("def ", "@")):
            first_calls += 1
        if ev == "line" and line == BODY_FIRST_LINE:
            iterations += 1

    if events == 0:
        fail("no trace events for target function")
    if first_calls != 1:
        fail(f"expected exactly one generator invocation, found {first_calls}")
    if iterations == 0:
        fail("loop never iterated")

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iterations},
    }
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
