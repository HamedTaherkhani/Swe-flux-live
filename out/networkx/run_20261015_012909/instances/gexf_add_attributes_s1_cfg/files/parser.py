#!/usr/bin/env python
"""Derive the executed line path of one GEXFWriter.add_attributes invocation."""

import argparse
import json
import re
import sys

REL_FILE = "networkx/readwrite/gexf.py"
FUNC = "networkx.readwrite.gexf.GEXFWriter.add_attributes"
TARGET_INVOCATION = 10

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/gexf_add_attributes_s1_cfg/files/testcase.py::TestGexfAttributeSerialization::test_generate_gexf_mixed_attributes` "
    "(test file `networkx_qa/gexf_add_attributes_s1_cfg/files/testcase.py`, class `TestGexfAttributeSerialization`, "
    "single test method `test_generate_gexf_mixed_attributes`), run with the repository's Python (CPython 3.12) from the repo root. "
    "During this test, the method `GEXFWriter.add_attributes` defined in `networkx/readwrite/gexf.py` "
    "(fully qualified `networkx.readwrite.gexf.GEXFWriter.add_attributes`) is invoked several times, indirectly via "
    "`nx.generate_gexf`. Count invocations 1-based in chronological order of the function being entered "
    "(one invocation = one call of this function, from any caller, including calls that return early). "
    "For the 10th invocation, give the exact ordered sequence of executed line events inside that invocation's own frame. "
    "Definition of a line event: exactly the events that a `sys.settrace` local trace function receives with event "
    "`'line'` for that frame, reporting `frame.f_lineno` at each event, in the order received. Consequences that you must respect: "
    "the `def` line is NOT included (entering the function is a `'call'` event, not a `'line'` event), nor is the `'return'` event; "
    "lines executed in other frames (callees such as `get_attr_id`, `alter_graph_mode_timeformat`, `Element`, `str`, etc.) are NOT included; "
    "a `for` header line produces an event each time the loop asks for its next item, including the final check that ends "
    "the loop (but no event is produced for a `for` header when the loop is left via `break`); "
    "no deduplication or collapsing is applied - every repeated execution of a line is a separate element. "
    "Multi-line statements: this function contains multi-line assignment statements whose right-hand side is a call spanning "
    "several physical lines (`attr_id = self.get_attr_id(` followed by an argument line and a closing parenthesis line). "
    "Under CPython 3.12 these are reported the way the interpreter actually reports them: an event on the line where the "
    "statement begins, then an event on the argument continuation line, then again an event on the line where the statement "
    "begins (the closing-parenthesis line produces no event); include all of these events as reported. "
    "Line numbers are absolute, 1-based line numbers in `networkx/readwrite/gexf.py` as it exists in this repository. "
    "Answer format: a JSON object `{\"executed_path\": [...]}` whose list contains one object per line event, in "
    "chronological order, each with exactly the keys `file` (string, the repo-relative path `networkx/readwrite/gexf.py`), "
    "`func` (string, the dotted `module.qualname`, i.e. `networkx.readwrite.gexf.GEXFWriter.add_attributes`; identical in every element) "
    "and `line` (integer)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {path}")
    if not raw:
        fail("trace log is empty")
    invocations = []
    current = None
    for text in raw:
        m = LINE_RE.match(text)
        if not m:
            continue
        if m.group("func") != FUNC or not m.group("file").endswith(REL_FILE):
            continue
        event = m.group("event")
        line = int(m.group("line"))
        if event == "call":
            if current is not None:
                fail("nested/unterminated invocation of target (unexpected)")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("line event outside an invocation")
            current.append(line)
        elif event == "return":
            current = None
    if not invocations:
        fail("zero events for target function in trace")
    return invocations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    invocations = parse(args.trace_log)
    for i, inv in enumerate(invocations, 1):
        print(f"invocation {i}: {len(inv)} line events", file=sys.stderr)
    if len(invocations) < TARGET_INVOCATION:
        fail(f"only {len(invocations)} invocations, need {TARGET_INVOCATION}")
    path = invocations[TARGET_INVOCATION - 1]
    if not path:
        fail("selected invocation has no line events")

    answer = {
        "executed_path": [
            {"file": REL_FILE, "func": FUNC, "line": ln} for ln in path
        ]
    }
    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
