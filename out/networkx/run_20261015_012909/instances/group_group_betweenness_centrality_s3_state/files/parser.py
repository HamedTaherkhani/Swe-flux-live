#!/usr/bin/env python
"""Derive the S3_ProgramState oracle (value history of ``GBC_group``) for
group_betweenness_centrality from a trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_SUFFIX = "networkx/algorithms/centrality/group.py"
TARGET_QUALNAME = "networkx.algorithms.centrality.group.group_betweenness_centrality"
VARIABLE = "GBC_group"
TEST_FILE = "networkx_qa/group_group_betweenness_centrality_s3_state/files/testcase.py"
TEST_CLASS = "TestGroupBetweennessHistory"
TEST_METHOD = "test_multi_group_unnormalized"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
    r"(?:retval=.*? )?locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    f"Run the single pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` "
    f"(test file `{TEST_FILE}`, class `{TEST_CLASS}`, method `{TEST_METHOD}`) under "
    "CPython 3.12. During this test the function "
    "`networkx.algorithms.centrality.group.group_betweenness_centrality` (defined in "
    "`networkx/algorithms/centrality/group.py`) is invoked exactly once (one `call` of "
    "the function's own frame; the `nx._dispatchable` wrapper is not a separate "
    "invocation). Report the complete ordered history of values bound to the local "
    "variable `GBC_group` in that invocation's frame. A history step is recorded every "
    "time a statement that assigns `GBC_group` finishes executing: the plain assignment "
    "`GBC_group = 0` and every augmented assignment (`+=`, `-=`, `/=`) to `GBC_group`, "
    "in chronological execution order, over all groups processed by the outer "
    "`for group in C` loop. Every such execution is a step, even if the new value has the "
    "same repr as the previous one (no deduplication). Each value is Python `repr()` of "
    "the object bound to `GBC_group` immediately after that statement executed, emitted as a "
    "JSON string containing exactly the repr text with no added quotes (so an int 3 is "
    "written as the JSON string \"3\", a float uses CPython's shortest round-trip repr, "
    "e.g. \"2.5\" or \"-0.75\", never rounded or reformatted; an int and a float of equal "
    "value are different reprs, e.g. \"4\" vs \"4.0\"). "
    'Answer with JSON of the form {"value_history": [{"step": <int>, "value": <str>}, ...]} '
    "where `step` is 1-based and increases by one per recorded assignment, and the list "
    "is ordered by `step` ascending."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def assign_lines(src_path):
    """Lines of statements in the target that (aug)assign VARIABLE."""
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "group_betweenness_centrality":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    if any(isinstance(t, ast.Name) and t.id == VARIABLE for t in sub.targets):
                        lines.add(sub.lineno)
                elif isinstance(sub, ast.AugAssign):
                    if isinstance(sub.target, ast.Name) and sub.target.id == VARIABLE:
                        lines.add(sub.lineno)
    if not lines:
        fail("no assignment lines for variable found in source")
    return lines


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

    src_path = None
    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_SUFFIX):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        src_path = m.group("file")
        events.append(
            (m.group("event"), int(m.group("lineno")), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("zero events for the target function in trace")

    calls = sum(1 for e in events if e[0] == "call")
    if calls != 1:
        fail(f"expected exactly one invocation, found {calls}")

    alines = assign_lines(src_path)
    state = {}
    pending = False
    history = []
    for event, lineno, locs in events:
        state.update(locs)
        if pending:
            if VARIABLE not in state:
                fail("variable missing after its assignment")
            val = state[VARIABLE]
            if val.endswith("..."):
                fail("truncated repr in trace")
            history.append(val)
            pending = False
        if event == "line" and lineno in alines:
            pending = True
    if pending:
        fail("trace ended right after an assignment")
    if not history:
        fail("no assignments recorded")

    answer = {
        "value_history": [
            {"step": i, "value": v} for i, v in enumerate(history, start=1)
        ]
    }
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"value_history": [{"step": "int", "value": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
