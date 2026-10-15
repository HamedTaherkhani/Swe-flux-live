#!/usr/bin/env python
"""Parse the tracer log into oracle.json for isomorphvf2_syntactic_feasibility_s1_cfg_2.

Answer: the ordered list of `line` events recorded inside the K-th invocation
(1-based, ordered by `call` events) of GraphMatcher.syntactic_feasibility.
Every line event is kept (no dedup, no collapsing); the `call` and `return`
events themselves are not part of the path.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "networkx/algorithms/isomorphism/isomorphvf2.py"
TARGET_QUALNAME = "networkx.algorithms.isomorphism.isomorphvf2.GraphMatcher.syntactic_feasibility"
TARGET_K = 23
TEST_ID = (
    "networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg_2/files/testcase.py"
    "::TestSyntacticFeasibilityDirect::test_candidate_pairs_after_partial_mapping"
)

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
)

QUESTION = f"""\
Consider the pytest test `{TEST_ID}` (file `networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg_2/files/testcase.py`, test class `TestSyntacticFeasibilityDirect`, its single test method `test_candidate_pairs_after_partial_mapping`). The test builds two seeded graphs, seeds a partial mapping with `GMState`, and then calls `GraphMatcher.syntactic_feasibility` directly for many candidate pairs.

Target function: `GraphMatcher.syntactic_feasibility` defined in `{TARGET_FILE}` (dotted qualname `{TARGET_QUALNAME}`).

Invocations are counted 1-based in chronological order of the function being entered (each Python-level call of this function during the test run counts as one invocation; there is no recursion). Report the exact ordered control-flow path of invocation number {TARGET_K}.

The path is the chronological sequence of every "line" event that CPython's `sys.settrace` line tracing (the interpreter in this repository's environment, Python 3.12) reports for that invocation's own frame, from function entry until it returns. Rules:
- Include every line event, in order, with NO deduplication and NO collapsing of repeated or consecutive lines; a loop header line (`for ...:`) appears once each time it is evaluated, including the final evaluation that exhausts the loop.
- The `def` line, the docstring, and comment lines never appear; the function-entry ("call") and "return" events are not elements of the path.
- Line events inside other functions called from the target (e.g. `number_of_edges`, graph `__getitem__`) are NOT included.
- This function contains multi-line `if`/`elif` conditions (e.g. a condition starting with `if self.G1.number_of_edges(` that continues onto following lines). Do not normalize these: report exactly the line numbers the interpreter emits as line events, which in Python 3.12 can include continuation lines of a multi-line expression and can return to the statement's first line while evaluating it.
- Line numbers are absolute, 1-based line numbers of `{TARGET_FILE}` as it exists in the repository.

Answer format: a JSON object `{{"executed_path": [...]}}` where each element is `{{"file": <str>, "func": <str>, "line": <int>}}`. `file` is always the repo-relative path `{TARGET_FILE}`, `func` is always the dotted qualname `{TARGET_QUALNAME}` (identical in every element), and `line` is the integer line number. The list is ordered by execution order (first executed line first)."""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


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

    invocations = []
    current = None
    n_events = 0
    for raw in text.splitlines():
        if "[TRACE]" in raw:
            continue
        m = LINE_RE.match(raw)
        if not m or m["func"] != TARGET_QUALNAME:
            continue
        if not m["file"].replace("\\", "/").endswith(TARGET_FILE):
            continue
        n_events += 1
        event = m["event"]
        lineno = int(m["lineno"])
        if event == "call":
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("line event before any call event")
            current.append(lineno)
        elif event in ("return", "exception"):
            pass
    if n_events == 0:
        fail(f"no events for {TARGET_QUALNAME} in {p}")
    if len(invocations) < TARGET_K:
        fail(f"only {len(invocations)} invocations, need {TARGET_K}")
    path = invocations[TARGET_K - 1]
    if not path:
        fail(f"invocation {TARGET_K} has no line events")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_FILE, "func": TARGET_QUALNAME, "line": ln}
                for ln in path
            ]
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} k={TARGET_K} path_len={len(path)}")


if __name__ == "__main__":
    main()
