#!/usr/bin/env python
"""Trace -> oracle.json for simple_paths_bidirectional_dijkstra_s6_calls."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/algorithms/simple_paths.py"
MODULE = "networkx.algorithms.simple_paths"
TARGET = f"{MODULE}._bidirectional_dijkstra"
INVOCATION = 2

EVENT_RE = re.compile(r"\s(\S+\.py):(\d+) (\S+) event=(call|line|return|exception)\b")

TEST_FILE = "networkx_qa/simple_paths_bidirectional_dijkstra_s6_calls/files/testcase.py"
TEST_CLASS = "TestBidirectionalDijkstraFiltered"
TEST_METHOD = "test_filtered_bidirectional_searches"

QUESTION = f"""\
Test: `{TEST_FILE}`, class `{TEST_CLASS}`, method `{TEST_METHOD}` \
(pytest id `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}`). The test is the only test method in the file.

Target function: `{TARGET}` (file `{REL_FILE}`), which the test calls directly.

Number the invocations of `_bidirectional_dijkstra` 1, 2, 3, ... in chronological order of their Python \
`call` events (function entry) during the test run. Consider ONLY invocation number {INVOCATION}.

Tracked functions: exactly the functions defined (at any nesting level) inside `_bidirectional_dijkstra`, i.e.
  - `{TARGET}.<locals>.filter_iter`
  - `{TARGET}.<locals>.filter_iter.<locals>.iterate`
  - `{TARGET}.<locals>.filter_pred_iter`
  - `{TARGET}.<locals>.filter_pred_iter.<locals>.iterate`
  - `{TARGET}.<locals>.filter_succ_iter`
  - `{TARGET}.<locals>.filter_succ_iter.<locals>.iterate`
(The target contains two separate `def filter_iter` blocks with the same qualname; both are written with \
the same name above and are not distinguished.)

Report the chronological sequence of Python `call` events of tracked functions that occur while invocation \
{INVOCATION} of the target is on the call stack (between its entry and its return/exception exit), \
including nested/transitive calls (e.g. one tracked generator starting another), not only calls made \
directly from the target's own frame. Counting rules:
  - `filter_iter`, `filter_pred_iter`, `filter_succ_iter` are ordinary functions: every call is one element.
  - The `iterate` functions are generator functions. Calling `iterate(v)` merely creates a generator object \
and is NOT counted. A generator contributes exactly ONE element, at the moment its body first starts \
executing (the first `next()` on it). Later resumptions after a `yield`, and any `close()`/`throw()`, are \
NOT counted.
  - Repeated calls are listed every time (no deduplication). Calls to any other function (graph methods such \
as `G.successors`/`G.predecessors`, the weight function, `heappush`/`heappop`, builtins, functions in other \
modules) and the target itself are excluded.

Answer format: JSON object `{{"function_call_order": [{{"file": str, "func": str}}, ...]}}`, one element per \
counted call in chronological order, where `file` is the repo-relative path `{REL_FILE}` and `func` is the \
dotted `module.qualname` of the called function using Python's `__qualname__` including `<locals>` \
components — e.g. a nested function `helper` inside `pkg.mod.outer` is written `pkg.mod.outer.<locals>.helper`."""


def generator_def_lines(src_path):
    """def-line numbers of generator functions nested in the target."""
    tree = ast.parse(Path(src_path).read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == TARGET.rsplit(".", 1)[1]:
            for sub in ast.walk(node):
                if isinstance(sub, ast.FunctionDef) and sub is not node:
                    if any(
                        isinstance(x, (ast.Yield, ast.YieldFrom)) for x in ast.walk(sub)
                    ):
                        out.add(sub.lineno)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=REL_FILE)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log missing: {args.trace_log}")
    if not lines:
        sys.exit("ERROR: trace log is empty")

    gen_lines = generator_def_lines(args.src)
    if not gen_lines:
        sys.exit("ERROR: no nested generator functions found in target source")

    events = []
    for line in lines:
        m = EVENT_RE.search(line)
        if not m:
            continue
        path, lineno, func, ev = m.groups()
        if not path.replace("\\", "/").endswith(REL_FILE):
            continue
        events.append((func, ev, int(lineno)))

    if not any(f == TARGET for f, _, _ in events):
        sys.exit("ERROR: zero trace events for target function")

    nested_prefix = TARGET + ".<locals>."
    per_inv = []
    inv = 0
    depth = 0
    cur = None
    for func, ev, lineno in events:
        if func == TARGET:
            if ev == "call":
                inv += 1
                depth += 1
                if depth == 1:
                    cur = []
            elif ev == "return":
                depth -= 1
                if depth == 0:
                    per_inv.append(cur)
                    cur = None
            continue
        if cur is None or ev != "call" or not func.startswith(nested_prefix):
            continue
        if func.endswith(".<locals>.iterate"):
            # generator: count only the initial start (call event on its def line)
            if lineno not in gen_lines:
                continue
        cur.append({"file": REL_FILE, "func": func})

    if depth != 0:
        sys.exit("ERROR: unbalanced target call/return events")
    if len(per_inv) < INVOCATION:
        sys.exit(f"ERROR: only {len(per_inv)} invocations of target traced")
    seq = per_inv[INVOCATION - 1]
    if not seq:
        sys.exit("ERROR: no tracked calls in requested invocation")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2)
        fh.write("\n")
    print("tracked calls per invocation:", [len(s) for s in per_inv])
    abbrev = {"filter_iter": "F", "filter_pred_iter": "P", "filter_succ_iter": "S"}
    print(
        " ".join(
            abbrev[e["func"].split(".<locals>.")[1]]
            + ("i" if e["func"].endswith("iterate") else "")
            for e in seq
        )
    )


if __name__ == "__main__":
    main()
