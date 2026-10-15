#!/usr/bin/env python
"""Trace -> oracle.json for optimize_optimize_s2_loops (S2_Loops)."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_REL = "optuna/study/_optimize.py"
MODULE = "optuna.study._optimize"
FUNC_NAME = "_optimize"
TARGET_QUALNAME = f"{MODULE}.{FUNC_NAME}"
TEST_FILE = "optuna_qa/optimize_optimize_s2_loops/files/testcase.py"
TEST_CLASS = "TestOptimizeInlineParallel"
TEST_METHOD = "test_parallel_submission_loop_until_stop"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(src_path: Path) -> tuple[int, int]:
    """Return (header line, first body line) of the `itertools.count()` for-loop."""
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == FUNC_NAME),
        None,
    )
    if func is None:
        fail(f"{FUNC_NAME} not found in {src_path}")
    loops = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.For)
        and isinstance(n.iter, ast.Call)
        and ast.unparse(n.iter.func) == "itertools.count"
    ]
    if len(loops) != 1:
        fail(f"expected exactly one itertools.count() loop, found {len(loops)}")
    return loops[0].lineno, loops[0].body[0].lineno


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace_path}")

    root = Path(__file__).resolve().parents[3]
    src_path = root / TARGET_REL
    if not src_path.is_file():
        src_path = Path.cwd() / TARGET_REL
    header, body_first = find_loop(src_path)

    n_calls = 0
    n_target_events = 0
    body_hits = 0
    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        n_target_events += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "line" and int(m.group("lineno")) == body_first and n_calls == 1:
            body_hits += 1

    if n_target_events == 0:
        fail(f"no trace events for {TARGET_QUALNAME}")
    if n_calls != 1:
        fail(f"expected exactly 1 invocation of {TARGET_QUALNAME}, got {n_calls}")
    if body_hits == 0:
        fail(f"loop at line {header} never iterated")

    question = f"""\
Run the single test method `{TEST_METHOD}` of class `{TEST_CLASS}` in `{TEST_FILE}` (pytest id `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}`). During that test the function `{TARGET_QUALNAME}` (defined in `{TARGET_REL}`) is invoked exactly once (invocation = one `call` of that function, 1-based, chronological; this question concerns invocation 1).

Consider the `for` loop whose header is at line {header} of `{TARGET_REL}` (absolute 1-based line number in the file as it exists in the repository): `for n_submitted_trials in itertools.count():`. Define one iteration as one execution of the first line of that loop's body, line {body_first} (`if study._stop_flag:`). An iteration counts even if it ends immediately with `break` on that line or a later line of the body; so the final pass that exits via a `break` IS counted. Iterations are counted only for this one invocation of `{TARGET_QUALNAME}`; executions of lines in other functions (e.g. `_optimize_sequential`, whose own `while` loop is unrelated) do not count.

How many iterations does this loop perform? Answer as a JSON object `{{"loop_iteration_count": <int>}}` where the value is a plain JSON integer (not a string).
"""

    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": body_hits},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
