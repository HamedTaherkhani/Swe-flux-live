#!/usr/bin/env python
"""Build oracle.json for optimization_history_get_optimization_history_plot_m2_loops."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


REL_FILE = "optuna/visualization/_optimization_history.py"
FUNC_NAME = "_get_optimization_history_plot"
QUALNAME = "optuna.visualization._optimization_history._get_optimization_history_plot"
TEST_PATH = "optuna_qa/optimization_history_get_optimization_history_plot_m2_loops/files/testcase.py"
TEST_CLASS = "TestOptimizationHistoryPlotLoops"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def locate_lines(root: Path) -> dict[str, int]:
    src = (root / REL_FILE).read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == FUNC_NAME), None
    )
    if func is None:
        fail(f"{FUNC_NAME} not found in {REL_FILE}")
    outer = next(n for n in func.body if isinstance(n, ast.For))
    branch = next(n for n in outer.body if isinstance(n, ast.If))
    inner = [n for n in branch.body if isinstance(n, ast.For)]
    if len(inner) != 2:
        fail("expected two inner for-loops in the `stds is None` branch")
    return {
        "outer_header": outer.lineno,
        "outer_body": outer.body[0].lineno,
        "branch_header": branch.lineno,
        "branch_first": branch.body[0].lineno,
        "feasible_header": inner[0].lineno,
        "feasible_body": inner[0].body[0].lineno,
        "infeasible_header": inner[1].lineno,
        "infeasible_body": inner[1].body[0].lineno,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    root = Path.cwd()
    L = locate_lines(root)

    events = []
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if m.group("func") != QUALNAME or not m.group("file").endswith(REL_FILE):
            continue
        events.append((m.group("event"), int(m.group("line"))))
    if not events:
        fail("no trace events for target function")
    n_calls = sum(1 for e, _ in events if e == "call")
    if n_calls == 0:
        fail("no call events for target function")

    # Each outer-loop iteration: [took_plain_branch, inner_iteration_count]
    outer_iters: list[list] = []
    current = None
    for ev, line in events:
        if ev == "call" or ev == "return":
            current = None
            continue
        if ev != "line":
            continue
        if line == L["outer_body"]:
            current = [False, 0]
            outer_iters.append(current)
        elif current is not None:
            if line == L["branch_first"]:
                current[0] = True
            elif line in (L["feasible_body"], L["infeasible_body"]):
                current[1] += 1

    counts = [c for plain, c in outer_iters if plain]
    if not counts:
        fail("no outer-loop iterations took the `stds is None` branch")

    question = f"""\
Consider ALL test methods of the pytest test class `{TEST_CLASS}` in `{TEST_PATH}` \
(i.e. run `pytest {TEST_PATH}::{TEST_CLASS}` from the repository root; every `test_*` method \
of the class is run, and the answer aggregates over all of them together).

The target is the function `{QUALNAME}` defined at module level in `{REL_FILE}`. Every call \
of this function made during the run counts as one invocation (all invocations of all test \
methods are pooled; their order does not matter for the answer).

Inside this function there is an outer `for` loop whose header is on line {L["outer_header"]} \
(`for trial_numbers, values_info, best_values_info in info_list:`). One OUTER ITERATION is one \
execution of that loop's body first line (line {L["outer_body"]}), counted across all \
invocations. Inside the `if values_info.stds is None:` branch of the outer body there are two \
nested `for` loops: the loop with header on line {L["feasible_header"]} (body line \
{L["feasible_body"]}) and the loop with header on line {L["infeasible_header"]} (body line \
{L["infeasible_body"]}). (Line numbers are absolute, 1-based line numbers of `{REL_FILE}` as it \
exists in the repository.)

For each outer iteration, define its INNER ITERATION COUNT as the number of times line \
{L["feasible_body"]} executes plus the number of times line {L["infeasible_body"]} executes \
during that outer iteration (i.e. the total number of iterations of both nested loops combined \
within that one outer iteration; an inner iteration = one execution of the nested loop body's \
first line). List comprehensions are not loops for this purpose and are not counted.

Consider only those outer iterations that take the `values_info.stds is None` branch (the \
condition on line {L["branch_header"]} is true); outer iterations taking the `else` branch \
are ignored entirely. An outer iteration in which the branch is taken but neither nested loop \
iterates has inner iteration count 0 and IS included.

Report, over all those outer iterations across all invocations in all test methods:
- `max_iterations`: the largest inner iteration count (a JSON integer);
- `min_iterations`: the smallest inner iteration count (a JSON integer).

Answer as a JSON object with exactly the keys `max_iterations` and `min_iterations`."""

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {"max_iterations": max(counts), "min_iterations": min(counts)},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(f"invocations={n_calls} plain_outer_iterations={len(counts)} counts={counts}")


if __name__ == "__main__":
    main()
