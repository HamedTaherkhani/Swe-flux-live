"""Derive the S1 oracle (executed path of one invocation) from the trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/algorithms/isomorphism/isomorphvf2.py"
CLASS_NAME = "DiGraphMatcher"
METHOD_NAME = "syntactic_feasibility"
QUALNAME = f"networkx.algorithms.isomorphism.isomorphvf2.{CLASS_NAME}.{METHOD_NAME}"
INVOCATION = 16

LINE_RE = re.compile(r"\s(?P<file>/\S+?\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Test: `networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg/files/testcase.py`, class `TestDiGraphSubgraphSearch`, test method `test_induced_subgraph_embeddings` (pytest id `networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg/files/testcase.py::TestDiGraphSubgraphSearch::test_induced_subgraph_embeddings`).

Target function: `{CLASS_NAME}.{METHOD_NAME}` defined in `{REL_FILE}` (dotted name `{QUALNAME}`). Only this method counts; `GraphMatcher.{METHOD_NAME}` in the same file and methods of subclasses in other files are NOT the target.

Invocation counting: number the calls (Python function-call entries into a new frame of the target) that happen while this test method runs, 1-based, in chronological order, counting every call regardless of who the caller is. Consider invocation number {INVOCATION}.

Question: what is the exact ordered sequence of executed source lines inside the target function during invocation {INVOCATION}, from function entry until it returns?

Line-event rules:
- Report one entry each time Python's line tracer (`sys.settrace` "line" events, CPython 3.12 as installed in this repository's environment) reports a line executing in that invocation's own frame. Lines executed in other functions called by the target (e.g. `number_of_edges`, graph views) are NOT included.
- The `def` line, the docstring and comments never appear. The function-entry ("call") and function-exit ("return") events themselves are not entries; the final `return` statement appears exactly once as a normal executed line.
- Several statements in this function span multiple physical lines (e.g. `if` conditions comparing two `number_of_edges(...)` calls written over 2-3 lines). Any line event that falls on a continuation line of a statement (or of a compound statement's header such as an `if`/`elif` condition) is reported as the line number where that statement begins (the line containing `if`/`elif`). After this mapping, collapse every run of consecutive identical line numbers into a single entry (within this function a single statement never legitimately executes twice back-to-back, so such runs only come from a multi-line statement being evaluated).
- A `for` header line is reported every time it is reported by the tracer: on loop entry, before each further iteration, and the final check when the iterator is exhausted. `elif`/`else` follow Python 3.12 tracing: an `elif` line appears when its condition is evaluated; an `else:` line itself never appears (only the first statement inside it).
- Line numbers are absolute, 1-based line numbers in `{REL_FILE}` as it exists in the repository.

Answer format: a JSON object `{{"executed_path": [...]}}` where each element is `{{"file": str, "func": str, "line": int}}`, in execution order (no sorting, no deduplication beyond the consecutive-run collapse described above). `file` is always the repo-relative path `{REL_FILE}` and `func` is always the dotted name `{QUALNAME}` (identical in every element); `line` is a JSON integer.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def statement_start_map(src_path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == METHOD_NAME:
                    func = item
    if func is None:
        fail("target function not found in source")
    spans = []
    for node in ast.walk(func):
        if node is func or not isinstance(node, ast.stmt):
            continue
        if isinstance(node, (ast.If, ast.While)):
            end = node.test.end_lineno
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            end = max(node.iter.end_lineno, node.target.end_lineno)
        elif hasattr(node, "body"):
            end = node.lineno
        else:
            end = node.end_lineno
        spans.append((node.lineno, end))
    mapping = {}
    for start, end in spans:
        for ln in range(start, end + 1):
            prev = mapping.get(ln)
            if prev is None or (end - start) < (prev[1] - prev[0]):
                mapping[ln] = (start, end)
    return {ln: se[0] for ln, se in mapping.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    invocations = []
    current = None
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        if m.group("func") != QUALNAME:
            continue
        ev = m.group("event")
        if ev == "call":
            current = []
            invocations.append(current)
        elif ev == "line":
            if current is None:
                fail("line event before any call event")
            current.append(int(m.group("line")))
    if not invocations:
        fail("zero call events for the target function in trace")
    if len(invocations) < INVOCATION:
        fail(f"only {len(invocations)} invocations traced; need {INVOCATION}")

    src = Path(__file__).resolve().parents[3] / REL_FILE
    if not src.is_file():
        src = Path.cwd() / REL_FILE
    stmt_start = statement_start_map(src)

    path = []
    for ln in invocations[INVOCATION - 1]:
        if ln not in stmt_start:
            fail(f"line {ln} not inside a statement of the target")
        mapped = stmt_start[ln]
        if path and path[-1] == mapped:
            continue
        path.append(mapped)
    if not path:
        fail("selected invocation has no line events")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {
            "executed_path": [{"file": REL_FILE, "func": QUALNAME, "line": ln} for ln in path]
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"invocations traced: {len(invocations)}; path length: {len(path)}")


if __name__ == "__main__":
    main()
