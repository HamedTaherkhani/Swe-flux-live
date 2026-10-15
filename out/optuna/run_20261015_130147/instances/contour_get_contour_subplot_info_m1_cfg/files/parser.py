#!/usr/bin/env python
"""Build oracle.json for contour_get_contour_subplot_info_m1_cfg."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


REL_FILE = "optuna/visualization/_contour.py"
FUNC_NAME = "_get_contour_subplot_info"
QUALNAME = "optuna.visualization._contour._get_contour_subplot_info"
TEST_PATH = "optuna_qa/contour_get_contour_subplot_info_m1_cfg/files/testcase.py"
TEST_CLASS = "TestContourSubplots"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def function_span(source: str) -> tuple[int, int]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            return node.lineno, node.end_lineno
    fail(f"function {FUNC_NAME} not found in {REL_FILE}")
    raise AssertionError


def build_question(def_line: int, first: int, last: int) -> str:
    return f"""\
Consider the pytest test class `{TEST_PATH}::{TEST_CLASS}` (file `{TEST_PATH}`, class \
`{TEST_CLASS}`), run from the repository root with CPython 3.11 as \
`pytest {TEST_PATH}::{TEST_CLASS}`. The answer aggregates over ALL test methods \
(`def test_...`) of this class; every method runs exactly once, in the same process, and \
all of them contribute.

Target function: `{QUALNAME}`, defined at module level in `{REL_FILE}` (its `def` line is \
line {def_line} and the function's last physical line is line {last}). The test never calls \
it directly; it is reached through `optuna.visualization.plot_contour`, and every call made \
during any test method counts, however many times it is called per method (possibly zero).

Question: for every physical source line from line {first} through line {last} \
(inclusive) of `{REL_FILE}`, how many times was that line executed in total during the \
whole test class run?

Definition of "executed": count the `line` events that CPython's `sys.settrace` line \
tracing reports for that line number in frames whose code object is this function itself, \
summed over all invocations of the function in all test methods. Precisely:
- Only frames of `{QUALNAME}` itself count. Lines executed in callees (e.g. \
`_get_axis_info`, `_satisfy_constraints`, logger methods, the `target` lambdas) do not \
count, and neither do lines of the separate list-comprehension frame \
(`<listcomp>`, which is its own frame on Python 3.11) - only the line events the \
function's own frame reports.
- `call` and `return` events are not counted; the `def` line ({def_line}) is outside the \
scope and receives no line events anyway. The signature continuation lines, blank lines, \
comment-only lines, `else:` lines, and closing-parenthesis lines are INCLUDED in the scope \
and simply get whatever number of line events the tracer reports for them (usually 0).
- Multi-line statements: do NOT remap events to the first line of the statement. Each \
physical line is credited with exactly the line events reported for that line number. A \
multi-line statement/expression may therefore produce events on several of its physical \
lines, and the same physical line may receive more than one event during a single \
execution of the statement - every reported event counts. A `for` header receives one \
event each time the loop condition is (re)checked, including the final check that ends \
the loop.

Answer format: a JSON object `{{"line_execution_counts": [...]}}`. The list has exactly one \
element per physical line from {first} to {last} inclusive (no line omitted, lines that \
never executed appear with `"count": 0`), each of the form `{{"line": <int>, "count": \
<int>}}`, where `line` is the absolute 1-based line number in `{REL_FILE}` as it exists in \
the repository and `count` is a non-negative JSON integer total. Sort the list by `line` \
ascending; there are no duplicate `line` values.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {trace_path}")

    repo_root = Path(__file__).resolve().parents[3]
    src_path = repo_root / REL_FILE
    if not src_path.is_file():
        src_path = Path.cwd() / REL_FILE
    source = src_path.read_text(encoding="utf-8")
    def_line, last = function_span(source)
    first = def_line + 1

    counts = {ln: 0 for ln in range(first, last + 1)}
    n_calls = 0
    n_events = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        if m.group("func") != QUALNAME:
            continue
        n_events += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "line":
            ln = int(m.group("line"))
            if ln not in counts:
                fail(f"line event outside function span: {ln}")
            counts[ln] += 1

    if n_events == 0 or n_calls == 0:
        fail(f"no events for {QUALNAME} in trace log")

    answer = {
        "line_execution_counts": [
            {"count": counts[ln], "line": ln} for ln in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(def_line, first, last),
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calls={n_calls} line_events={sum(counts.values())} "
          f"distinct_lines={sum(1 for v in counts.values() if v)}")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
