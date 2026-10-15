#!/usr/bin/env python
"""Build oracle.json for parallel_coordinate_get_parallel_coordinate_info_s1_cfg."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


REL_FILE = "optuna/visualization/_parallel_coordinate.py"
FUNC_NAME = "_get_parallel_coordinate_info"
QUALNAME = "optuna.visualization._parallel_coordinate._get_parallel_coordinate_info"
TARGET_INVOCATION = 2
TEST_PATH = (
    "optuna_qa/parallel_coordinate_get_parallel_coordinate_info_s1_cfg/files/testcase.py"
)
TEST_CLASS = "TestParallelCoordinateFlow"
TEST_METHOD = "test_three_plots"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Consider the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (file `{TEST_PATH}`, \
class `{TEST_CLASS}`, the single test method `{TEST_METHOD}`), run from the repository root.

During this test, the function `{QUALNAME}` (defined at module level in `{REL_FILE}`) is \
invoked several times (it is never called directly by the test). Invocations are counted \
1-based in chronological order of the function being entered (one invocation = one call of \
this function). Report the control-flow path of invocation number {TARGET_INVOCATION}.

Definition of the path:
1. Consider only the lines executed in the frame of this function itself during that \
invocation. Lines executed in other frames are excluded: callees, generator-expression \
frames, list/dict/set comprehension frames (on this Python version comprehensions run in their \
own frames), lambdas, and the body of any nested function defined inside it. The `def` line \
(and the signature lines) are NOT included: the sequence starts with the first statement of \
the body; there is no docstring.
2. Each time the interpreter starts (or re-reaches) a source line of this frame, i.e. each \
`line` event that `sys.settrace` would report for this frame, map that line number to the \
FIRST line of the innermost statement (Python `ast` statement node: assignment, expression \
statement, `if`/`elif` header, `for` header, `return`, `raise`, nested `def`, ...) that \
contains it. Many statements in this function span several physical lines (multi-line calls, \
multi-line conditional expressions, multi-line `tuple(...)`/list literals, the multi-line \
`_DimensionInfo(...)`/`_ParallelCoordinateInfo(...)` constructions, etc.); such a statement \
is reported as the line where the statement begins. An `elif` is reported at the line of the \
`elif` keyword; a `for` header is reported at the `for` line every time the loop fetches its \
next item, including the final fetch that exhausts the iterator.
3. After this mapping, collapse runs of consecutive identical line numbers into a single \
element (e.g. a mapped sequence 10, 10, 12, 10 becomes 10, 12, 10). No other deduplication \
is applied; repeated loop iterations remain fully listed in execution order.

Line numbers are absolute, 1-based line numbers of `{REL_FILE}` as it exists in the \
repository.

Answer format: a JSON object `{{"executed_path": [...]}}` whose list contains one object per \
element of the path, in execution order, each of the form \
`{{"file": "{REL_FILE}", "func": "{QUALNAME}", "line": <int>}}`. `file` is the repo-relative \
path and `func` the dotted module.qualname exactly as shown (identical in every element); \
`line` is a JSON integer.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def statement_start_map(source: str) -> dict[int, int]:
    tree = ast.parse(source)
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            func = node
            break
    if func is None:
        fail(f"function {FUNC_NAME} not found in {REL_FILE}")
    mapping: dict[int, int] = {}
    depth: dict[int, int] = {}

    def visit(stmt: ast.stmt, d: int) -> None:
        for ln in range(stmt.lineno, stmt.end_lineno + 1):
            if ln not in depth or d >= depth[ln]:
                depth[ln] = d
                mapping[ln] = stmt.lineno
        for field in ("body", "orelse", "finalbody", "handlers"):
            for child in getattr(stmt, field, []) or []:
                if isinstance(child, ast.stmt):
                    visit(child, d + 1)
                elif isinstance(child, ast.ExceptHandler):
                    for c in child.body:
                        visit(c, d + 2)

    for s in func.body:
        visit(s, 0)
    return mapping


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    src_path = Path.cwd() / REL_FILE
    if not src_path.is_file():
        fail(f"target source not found: {src_path}")
    smap = statement_start_map(src_path.read_text(encoding="utf-8"))

    invocations: list[list[int]] = []
    current: list[int] | None = None
    n_events = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(REL_FILE) or m.group("func") != QUALNAME:
            continue
        n_events += 1
        ev = m.group("event")
        ln = int(m.group("line"))
        if ev == "call":
            current = []
            invocations.append(current)
        elif ev == "line":
            if current is None:
                fail("line event before any call event")
            if ln not in smap:
                fail(f"line {ln} not inside function body")
            current.append(smap[ln])
        elif ev == "return":
            current = None

    if n_events == 0:
        fail("no events for target function in trace")
    if len(invocations) < TARGET_INVOCATION:
        fail(f"only {len(invocations)} invocations traced; need {TARGET_INVOCATION}")

    path: list[int] = []
    for ln in invocations[TARGET_INVOCATION - 1]:
        if not path or path[-1] != ln:
            path.append(ln)
    if not path:
        fail("empty path for target invocation")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {
            "executed_path": [{"file": REL_FILE, "func": QUALNAME, "line": ln} for ln in path]
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} path_len={len(path)}")
    print(" ".join(str(x) for x in path))


if __name__ == "__main__":
    main()
