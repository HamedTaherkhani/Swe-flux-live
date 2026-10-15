#!/usr/bin/env python
"""Parse the line trace of eppstein_matching into per-line execution counts."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

REL_FILE = "networkx/algorithms/bipartite/matching.py"
FUNC_NAME = "eppstein_matching"
QUALNAME = "networkx.algorithms.bipartite.matching.eppstein_matching"
TEST_FILE = "networkx_qa/matching_eppstein_matching_m1_cfg/files/testcase.py"
TEST_CLASS = "TestEppsteinMatchingProfiles"

EVENT_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def function_range(root):
    src = (root / REL_FILE).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            return node.lineno, node.end_lineno
    die(f"{FUNC_NAME} not found in {REL_FILE}")


def build_question(def_line, first, last):
    return (
        f"Run the pytest test class `{TEST_FILE}::{TEST_CLASS}` (all of its test "
        f"methods, i.e. every pytest id of the form `{TEST_FILE}::{TEST_CLASS}::test_*`). "
        f"Consider the module-level function `{QUALNAME}` (decorated with "
        f"`@nx._dispatchable`) whose `def` line is `{REL_FILE}:{def_line}`; its body spans "
        f"lines {first}-{last} inclusive of that file as it exists in the repository. "
        f"For EVERY physical line number L with {first} <= L <= {last}, report how many "
        f"times line L was executed in total, summed over all invocations of "
        f"`eppstein_matching` across ALL test methods of the class. "
        f"An 'execution' of a line is one 'line' event as reported by Python 3.12's "
        f"`sys.settrace` line tracing for a frame whose code object is "
        f"`eppstein_matching` itself. Rules: (1) only the frame of `eppstein_matching` "
        f"counts: line events in frames of the nested function `recurse` are NOT counted, "
        f"so lines belonging only to the body of `recurse` are reported with count 0; "
        f"however the `def recurse(v):` statement itself is executed by the outer frame "
        f"and counts whenever that frame executes it. Line events produced by the dict "
        f"comprehension are counted on the line where they fire (in Python 3.12 "
        f"comprehensions are inlined into the enclosing frame). Line events of other "
        f"functions called from the body (e.g. `bipartite_sets`, graph methods) are not "
        f"counted. (2) The `def` line ({def_line}) and the decorator line are out of "
        f"scope (function entry/'call' events are not counted). (3) For a statement "
        f"spanning several physical lines, use the line number reported in "
        f"`frame.f_lineno` for the line event. Loop headers (`for`/`while`) are counted "
        f"each time their line event fires, including the final check that exits the "
        f"loop. (4) Blank lines, comment lines, docstring lines, and any line that never "
        f"produces a line event are still included, with count 0. Output a JSON object "
        f"with a single key `line_execution_counts` whose value is a list of objects "
        f"`{{\"line\": <int>, \"count\": <int>}}`, one per line number in the range "
        f"(no omissions, no duplicates), sorted by `line` ascending. Both values are "
        f"JSON integers (e.g. `{{\"line\": 1, \"count\": 0}}`)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default="/testbed")
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        die(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        die(f"trace log empty: {trace_path}")

    def_line, end_line = function_range(Path(args.root))
    first, last = def_line + 1, end_line

    counts = Counter()
    calls = 0
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        if m.group("func") != QUALNAME:
            continue
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "line":
            counts[int(m.group("line"))] += 1

    if calls == 0 or not counts:
        die(f"no events for {QUALNAME} in trace")
    outside = [ln for ln in counts if not (first <= ln <= last)]
    if outside:
        die(f"line events outside function range: {sorted(outside)}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(ln, 0), "line": ln} for ln in range(first, last + 1)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(def_line, first, last),
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calls={calls} line_events={sum(counts.values())} distinct_lines={len(counts)}")
    for ln in range(first, last + 1):
        if counts.get(ln):
            print(f"  {ln}: {counts[ln]}")


if __name__ == "__main__":
    main()
