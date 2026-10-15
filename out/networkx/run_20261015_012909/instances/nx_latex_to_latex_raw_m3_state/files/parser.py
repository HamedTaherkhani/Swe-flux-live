#!/usr/bin/env python
"""Parse the tracer log into oracle.json for nx_latex_to_latex_raw_m3_state.

The tracer logs, for each event of a target frame, the locals whose repr
changed since the previous event of that frame (all locals on `call` and
`return`). Every assignment to `e_opts` is followed by another line event (or
the return event) of the same frame, so the set of `e_opts` reprs seen in the
log equals the set of values ever bound to `e_opts`.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.drawing.nx_latex.to_latex_raw"
TARGET_FILE = "networkx/drawing/nx_latex.py"
VARIABLE = "e_opts"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
    r"(?P<rest>.*)$"
)

QUESTION = (
    "Consider the pytest test class `TestLatexEdgeOptions` in "
    "`networkx_qa/nx_latex_to_latex_raw_m3_state/files/testcase.py`. Run ALL "
    "of its test methods (pytest ids "
    "`networkx_qa/nx_latex_to_latex_raw_m3_state/files/testcase.py::"
    "TestLatexEdgeOptions::test_...`; 12 methods) and aggregate over every "
    "invocation of the function `networkx.drawing.nx_latex.to_latex_raw` "
    "(file `networkx/drawing/nx_latex.py`) that happens during those tests, "
    "whichever caller reaches it (an invocation is one actual entry into the "
    "body of `to_latex_raw`; calls rejected by its decorator before the body "
    "starts do not count). "
    "Collect every value that is ever bound to the local variable `e_opts` "
    "inside `to_latex_raw` (by any of its assignment statements, in any "
    "iteration of the edge loop, in any invocation, including intermediate "
    "values that are later overwritten in the same iteration). "
    "Report the set of DISTINCT values as a list under the key "
    "`unique_values`, where each element is the Python `repr()` of the value "
    "(so a string value `ab` is reported as the 5-character string `'ab'` "
    "including the quotes, using Python's default repr quoting; an empty "
    "string is reported as `''`). Remove duplicates by comparing these repr "
    "strings, and sort the list in ascending order using Python's default "
    "`str` ordering (Unicode code point, lexicographic) on the repr strings. "
    'Answer format: {"unique_values": ["str", ...]}.'
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_locals(rest):
    idx = rest.find("locals=")
    while idx != -1:
        try:
            return ast.literal_eval(rest[idx + len("locals="):])
        except (ValueError, SyntaxError):
            idx = rest.find("locals=", idx + 1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = Path(args.trace_log)
    if not p.is_file():
        fail(f"trace log not found: {p}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {p}")

    n_events = 0
    n_calls = 0
    values = set()
    for raw in text.splitlines():
        if "[TRACE]" in raw:
            continue
        m = LINE_RE.match(raw)
        if not m or m["func"] != TARGET_QUALNAME:
            continue
        if not m["file"].replace("\\", "/").endswith(TARGET_FILE):
            continue
        n_events += 1
        if m["event"] == "call":
            n_calls += 1
        loc = parse_locals(m["rest"])
        if loc is None:
            fail(f"could not parse locals in line: {raw[:200]}")
        if VARIABLE in loc:
            v = loc[VARIABLE]
            if len(v) > 500 and v.endswith("..."):
                fail(f"truncated repr for {VARIABLE}: {v[:80]}")
            values.add(v)

    if n_events == 0:
        fail(f"no events for {TARGET_QUALNAME} in {p}")
    if not values:
        fail(f"variable {VARIABLE} never observed")

    answer = {"unique_values": sorted(values)}
    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": answer,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(f"invocations={n_calls} events={n_events} distinct={len(values)}")
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
