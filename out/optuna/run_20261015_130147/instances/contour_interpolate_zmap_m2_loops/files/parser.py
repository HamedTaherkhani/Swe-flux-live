#!/usr/bin/env python
"""Derive the M2_Loops oracle for optuna.visualization.matplotlib._contour._interpolate_zmap."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/visualization/matplotlib/_contour.py"
TARGET_QUALNAME = "optuna.visualization.matplotlib._contour._interpolate_zmap"
FUNC_NAME = "_interpolate_zmap"
LOOP_HEADER_LINE = 356

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the test class `TestMatplotlibContourInterpolation` in the file "
    "`optuna_qa/contour_interpolate_zmap_m2_loops/files/testcase.py`, run with pytest as "
    "`optuna_qa/contour_interpolate_zmap_m2_loops/files/testcase.py::"
    "TestMatplotlibContourInterpolation` (i.e. ALL 12 `test_*` methods of the class; the answer "
    "aggregates over all of them and does not depend on the order in which pytest runs them). "
    "The test methods never call the target directly; it is reached through "
    "`optuna.visualization.matplotlib.plot_contour` -> `_get_contour_plot` -> "
    "`_generate_contour_subplot` -> `_calculate_griddata`. Note that each test temporarily patches "
    "the module constant `optuna.visualization.matplotlib._contour.CONTOUR_POINT_NUM` while "
    "plotting, so the grid size (and thus the `contour_plot_num` argument) differs per test. "
    "The target function is `_interpolate_zmap` (qualified name "
    "`optuna.visualization.matplotlib._contour._interpolate_zmap`) in the file "
    "`optuna/visualization/matplotlib/_contour.py`. Line numbers are absolute and 1-based in that "
    "file as it exists in the repository. Focus on the innermost loop, whose header is at line 356, "
    "`for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):` (in the `else` branch of the "
    "`if (x, y) in zmap:` test, nested inside the loops at line 347 over `x` and line 348 over "
    "`y`). An iteration of this loop is one execution of its body's first line, line 357 "
    "(`if 0 <= x + dx < contour_plot_num and 0 <= y + dy < contour_plot_num:`), counted "
    "regardless of whether that condition is true or false. An invocation is one call of "
    "`optuna.visualization.matplotlib._contour._interpolate_zmap` during the test run (1-based, "
    "chronological); test methods in which the target is never called contribute 0. Count the "
    "iterations of the line-356 loop summed over every entry into it, over every invocation, and "
    "over all test methods of the class. What is the total number of iterations? Answer as a JSON "
    "object exactly of the form {\"total_iterations\": <int>} where the value is a plain JSON "
    "integer (not a string)."
)


def loop_body_first_line(src_path):
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.For, ast.While)) and sub.lineno == LOOP_HEADER_LINE:
                    return sub.body[0].lineno
    sys.exit(f"ERROR: no loop with header at line {LOOP_HEADER_LINE} in {FUNC_NAME}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    src = os.path.join(os.getcwd(), TARGET_REL)
    if not os.path.isfile(src):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        src = os.path.join(repo_root, TARGET_REL)
    body_line = loop_body_first_line(src)

    n_events = 0
    n_calls = 0
    n_returns = 0
    total = 0
    per_call = []
    with open(args.trace_log, encoding="utf-8") as f:
        for raw in f:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_REL):
                continue
            n_events += 1
            ev = m.group("event")
            if ev == "call":
                n_calls += 1
                per_call.append(0)
            elif ev == "return":
                n_returns += 1
            elif ev == "line" and int(m.group("lineno")) == body_line:
                if not per_call:
                    sys.exit("ERROR: loop body line seen before any call event")
                total += 1
                per_call[-1] += 1

    if n_events == 0 or n_calls == 0:
        sys.exit(f"ERROR: no trace events for {TARGET_QUALNAME}")
    if n_calls != n_returns:
        sys.exit(f"ERROR: unbalanced call/return events ({n_calls} vs {n_returns})")

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": total},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"invocations={n_calls} per_invocation={per_call} total={total}")
    print(json.dumps(oracle["oracle_answer"]))


if __name__ == "__main__":
    main()
