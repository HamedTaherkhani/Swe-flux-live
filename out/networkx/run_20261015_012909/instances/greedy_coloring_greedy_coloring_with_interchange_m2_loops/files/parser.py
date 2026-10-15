#!/usr/bin/env python
"""Parse the line trace of _greedy_coloring_with_interchange into oracle.json.

Answer: total number of iterations of the Kempe-chain BFS `while` loop
(header `while i < len(frontier):`) summed over every invocation of the
target during the whole test class run. One iteration = one execution of the
loop body's first line (`search_node = frontier[i]`).
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "networkx/algorithms/coloring/greedy_coloring.py"
TARGET_FUNC = "networkx.algorithms.coloring.greedy_coloring._greedy_coloring_with_interchange"
FUNC_NAME = "_greedy_coloring_with_interchange"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def locate_loop(src_path):
    tree = ast.parse(Path(src_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.While)
                    and isinstance(sub.test, ast.Compare)
                    and isinstance(sub.test.left, ast.Name)
                    and sub.test.left.id == "i"
                ):
                    return sub.lineno, sub.body[0].lineno
    fail("could not locate BFS while loop in target source")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path(__file__).resolve().parents[3] / TARGET_FILE
    if not src.is_file():
        src = Path.cwd() / TARGET_FILE
    header_line, body_line = locate_loop(src)

    n_events = 0
    n_calls = 0
    iterations = 0
    with trace.open(encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m or m["func"] != TARGET_FUNC or not m["file"].endswith(TARGET_FILE):
                continue
            n_events += 1
            if m["event"] == "call":
                n_calls += 1
            elif m["event"] == "line" and int(m["lineno"]) == body_line:
                iterations += 1
    if n_events == 0 or n_calls == 0:
        fail("trace contains zero events for the target function")

    question = (
        "Run every test method of the test class `TestGreedyColorInterchangeBatch` in "
        "`networkx_qa/greedy_coloring_greedy_coloring_with_interchange_m2_loops/files/testcase.py` "
        "(pytest id prefix "
        "`networkx_qa/greedy_coloring_greedy_coloring_with_interchange_m2_loops/files/testcase.py::TestGreedyColorInterchangeBatch::`; "
        "the answer aggregates over ALL test methods of the class). Those tests reach the private function "
        "`networkx.algorithms.coloring.greedy_coloring._greedy_coloring_with_interchange` "
        "(file `networkx/algorithms/coloring/greedy_coloring.py`) indirectly via `greedy_color(..., interchange=True)`. "
        f"Consider the innermost Kempe-chain breadth-first-search loop `while i < len(frontier):` whose header is at line {header_line} "
        f"of that file (nested inside the `while connected and col2 < k:` and `while connected and col1 < k:` loops). "
        f"One iteration of this loop is one execution of its body's first line, `search_node = frontier[i]` (line {body_line}). "
        "An invocation is one call of `_greedy_coloring_with_interchange`; the loop may be entered zero, one, or many times "
        "per invocation. What is the total number of iterations of this loop summed over every time it is entered, "
        "across every invocation of the function in all test methods of the class? Count every iteration, including those "
        "in passes where no color interchange ultimately happens. "
        'Answer as JSON {"total_iterations": <int>}, a plain base-10 integer (e.g. {"total_iterations": 7}).'
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": iterations},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=False) + "\n")
    print(f"invocations={n_calls} target_events={n_events} loop_line={header_line} body_line={body_line}")
    print(json.dumps(oracle["oracle_answer"]))


if __name__ == "__main__":
    main()
