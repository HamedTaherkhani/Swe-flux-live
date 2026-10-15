#!/usr/bin/env python
"""Trace -> oracle.json for graphml_add_graph_element_s2_loops (S2_Loops)."""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "networkx/readwrite/graphml.py"
TARGET_CLASS = "GraphMLWriterLxml"
TARGET_METHOD = "add_graph_element"
TARGET_QUALNAME = f"networkx.readwrite.graphml.{TARGET_CLASS}.{TARGET_METHOD}"
TEST_FILE = "networkx_qa/graphml_add_graph_element_s2_loops/files/testcase.py"
TEST_CLASS = "TestGraphMLLxmlMultigraph"
TEST_METHOD = "test_write_multigraph_with_mixed_edge_data"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def locate_loop(repo_root):
    """Return (header_line, body_first_line) of the inner `for k, v in d.items()`
    loop inside the second multigraph edge pass of the target."""
    path = os.path.join(repo_root, TARGET_FILE)
    tree = ast.parse(open(path, encoding="utf-8").read())
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_METHOD:
                    func = item
    if func is None:
        die("target function not found in source")
    for stmt in func.body:
        if (
            isinstance(stmt, ast.If)
            and isinstance(stmt.test, ast.Call)
            and getattr(stmt.test.func, "attr", None) == "is_multigraph"
        ):
            outer_loops = [s for s in stmt.body if isinstance(s, ast.For)]
            if len(outer_loops) != 2:
                die("unexpected multigraph branch structure")
            inner = outer_loops[1].body[0]
            if not isinstance(inner, ast.For):
                die("unexpected inner loop structure")
            return inner.lineno, inner.body[0].lineno
    die("multigraph branch not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo-root", default=os.getcwd())
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        die("trace log is empty")

    header, body_line = locate_loop(args.repo_root)

    events = []
    for ln in raw:
        m = LINE_RE.match(ln)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE) or m.group("func") != TARGET_QUALNAME:
            continue
        events.append((m.group("event"), int(m.group("line"))))
    if not events:
        die("zero trace events for target function")

    # Split into invocations (calls of the target, chronological, 1-based).
    invocations = []
    depth = 0
    for ev, line in events:
        if ev == "call":
            if depth == 0:
                invocations.append([])
            depth += 1
        elif ev == "return":
            depth -= 1
        elif depth > 0:
            invocations[-1].append((ev, line))
    if len(invocations) != 1:
        die(f"expected exactly 1 invocation of target, got {len(invocations)}")

    inv = invocations[0]
    count = sum(1 for ev, line in inv if ev == "line" and line == body_line)
    if count == 0:
        die("loop body never executed; scenario is broken")

    question = (
        f"Consider the pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` "
        f"(the file defines this single test method in class `{TEST_CLASS}`). "
        f"During this test run, the method `{TARGET_QUALNAME}` (defined in "
        f"`{TARGET_FILE}`) is called exactly once (invocation 1, the only call "
        f"to that function during the test; it is reached indirectly through "
        f"`networkx.write_graphml`, which with lxml installed is "
        f"`write_graphml_lxml`). Look at the `for` loop whose header is at line "
        f"{header} of `{TARGET_FILE}` (line numbers absolute and 1-based, as the "
        f"file exists in the repository). An iteration of this loop is defined as "
        f"one execution of the loop body's first line, line {body_line}; count "
        f"iterations cumulatively over every time the loop is entered during that "
        f"single invocation (the loop is nested inside an enclosing loop, so it is "
        f"entered multiple times; sum all of its body executions across all "
        f"entries). How many iterations does this loop execute in total during "
        f"invocation 1? Answer as JSON of the form "
        f'{{"loop_iteration_count": <int>}}, where the value is a plain JSON '
        f"integer (not a string), e.g. {{\"loop_iteration_count\": 7}}."
    )

    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
