#!/usr/bin/env python
"""Derive the M2_Loops oracle for optuna.study._dataframe._create_records_and_aggregate_column."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/study/_dataframe.py"
TARGET_QUALNAME = "optuna.study._dataframe._create_records_and_aggregate_column"
FUNC_NAME = "_create_records_and_aggregate_column"
LOOP_HEADER_LINE = 50

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the test class `TestTrialsDataframeExport` in the file "
    "`optuna_qa/dataframe_create_records_and_aggregate_column_m2_loops/files/testcase.py`, run with "
    "pytest as `optuna_qa/dataframe_create_records_and_aggregate_column_m2_loops/files/testcase.py::"
    "TestTrialsDataframeExport` (i.e. ALL 12 `test_*` methods of the class, in whatever order pytest "
    "runs them; the answer does not depend on the order). The test methods never call the target "
    "directly; it is reached through `optuna.study.Study.trials_dataframe` -> "
    "`optuna.study._dataframe._trials_dataframe`. The target function is "
    "`_create_records_and_aggregate_column` (qualified name "
    "`optuna.study._dataframe._create_records_and_aggregate_column`) in the file "
    "`optuna/study/_dataframe.py`. Line numbers are absolute and 1-based in that file as it exists "
    "in the repository. Focus on the loop whose header is at line 50, "
    "`for nested_attr, nested_value in value.items():` (the loop that expands dict-valued trial "
    "attributes, nested inside the per-trial loop at line 43 and the per-attribute loop at line 45). "
    "An iteration of this loop is one execution of its body's first line, line 51 "
    "(`record[(df_column, nested_attr)] = nested_value`). Count iterations summed over every entry "
    "into the loop (every trial x attribute combination that reaches it; entries with an empty dict "
    "contribute 0), over every invocation of the target function (an invocation is one call of "
    "`optuna.study._dataframe._create_records_and_aggregate_column`; test methods in which the "
    "target is never called contribute 0), and over all test methods of the class. Only the target "
    "function's own frame counts (the loop at line 50 is not in any nested function or "
    "comprehension). What is the total number of iterations? Answer as a JSON object exactly of the "
    "form {\"total_iterations\": <int>} where the value is a plain JSON integer (not a string)."
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
    total = 0
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
            elif ev == "line" and int(m.group("lineno")) == body_line:
                total += 1

    if n_events == 0 or n_calls == 0:
        sys.exit("ERROR: zero trace events / invocations for the target function")

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": total},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(oracle["oracle_answer"]))
    print(f"invocations={n_calls} target_events={n_events}")


if __name__ == "__main__":
    main()
