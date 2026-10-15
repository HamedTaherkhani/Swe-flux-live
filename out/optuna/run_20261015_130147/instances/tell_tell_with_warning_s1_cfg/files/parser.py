#!/usr/bin/env python
"""Build oracle.json for tell_tell_with_warning_s1_cfg."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


REL_FILE = "optuna/study/_tell.py"
FUNC_NAME = "_tell_with_warning"
QUALNAME = "optuna.study._tell._tell_with_warning"
TARGET_INVOCATION = 23
TEST_PATH = "optuna_qa/tell_tell_with_warning_s1_cfg/files/testcase.py"
TEST_CLASS = "TestTellWithWarningFlow"
TEST_METHOD = "test_many_tells"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Consider the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (file `{TEST_PATH}`, \
class `{TEST_CLASS}`, the single test method `{TEST_METHOD}`), run from the repository root.

During this test, the function `{QUALNAME}` (defined at module level in `{REL_FILE}`) is \
invoked many times. Invocations are counted 1-based in chronological order of the function \
being entered (one invocation = one call of this function), and EVERY call made during the \
test counts: the main call in each loop iteration, the extra `state=TrialState.FAIL` call made \
after a `ValueError` is caught, and the periodic re-tell call on an already-finished trial \
(including re-tell calls that raise). Report the control-flow path of invocation number \
{TARGET_INVOCATION}.

Definition of the path:
1. Consider only the lines executed in the frame of this function itself during that \
invocation. Lines executed in other frames are excluded: callees (e.g. `_get_frozen_trial`, \
`_check_state_and_values`, `_check_values_are_feasible`, `optuna_warn`, logger and sampler \
methods) and the list-comprehension frame (on this Python version, 3.11, a list comprehension \
runs in its own frame). The `def` line and signature lines are NOT included, and the \
docstring never appears: the sequence starts with the first executable statement of the body.
2. Each time the interpreter starts (or re-reaches) a source line of this frame, i.e. each \
`line` event that `sys.settrace` would report for this frame, map that line number to the \
FIRST line of the innermost statement (Python `ast` statement node: assignment, expression \
statement, `assert`, `if`/`elif` header, `try` header, `return`, `raise`, ...) that contains \
it. Some statements in this function span several physical lines (most notably the \
multi-line `_logger.info(...)` call whose f-string arguments are split over several lines); \
such a statement is reported as the line where the statement begins. An `elif` is reported \
at the line of the `elif` keyword; an `if`/`elif` header appears whenever its condition is \
evaluated, whether or not it is true. A `try:` header line appears exactly when \
`sys.settrace` reports a line event for it; statements inside the `finally:` block are \
reported at their own lines (the `finally:` keyword line itself is not a statement). If the \
invocation ends by raising, the path ends with the last line executed in this frame.
3. After this mapping, collapse runs of consecutive identical line numbers into a single \
element (e.g. a mapped sequence 10, 10, 12, 10 becomes 10, 12, 10). No other deduplication \
is applied.

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
