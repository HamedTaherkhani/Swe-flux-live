#!/usr/bin/env python
"""Derive the S2_Loops oracle for optuna.cli._convert_to_dict from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/cli.py"
TARGET_QUALNAME = "optuna.cli._convert_to_dict"
FUNC_NAME = "_convert_to_dict"
LOOP_HEADER_LINE = 125
INVOCATION = 1

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the pytest test "
    "`optuna_qa/cli_convert_to_dict_s2_loops/files/testcase.py::TestStudiesFlattenOutput::"
    "test_studies_flatten_json` (test class `TestStudiesFlattenOutput`, its single test method "
    "`test_studies_flatten_json`). During this test run, the function `_convert_to_dict` "
    "(qualified name `optuna.cli._convert_to_dict`) defined in the file `optuna/cli.py` is "
    "called (indirectly, via the `optuna studies` CLI command). Invocations are counted "
    "1-based, in chronological order of calls to `optuna.cli._convert_to_dict` during the "
    "test run. Look at the loop whose header is at line 125 of `optuna/cli.py` "
    "(the statement `for i, v in enumerate(value):`, inside the `flatten` branch), with "
    "absolute 1-based line numbers in the file as it exists in the repository. "
    "In the 1st invocation of `optuna.cli._convert_to_dict`, how many iterations does this "
    "loop execute in total? An iteration is defined as one execution of the loop body's first "
    "line (line 126, `row[f\"{column[0]}_{i}\"] = v`); the count is summed over every time "
    "the loop is entered during that single invocation (i.e. across all records and columns "
    "processed by the enclosing loops), and entries of the loop that run zero iterations "
    "contribute 0. Answer as a JSON object of the form {\"loop_iteration_count\": <int>} "
    "where the value is a plain JSON integer (not a string)."
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

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    src = os.path.join(repo_root, TARGET_REL)
    if not os.path.isfile(src):
        src = os.path.join(os.getcwd(), TARGET_REL)
    body_line = loop_body_first_line(src)

    invocations = []  # list of per-invocation line-event lists
    depth = 0
    n_events = 0
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
                if depth != 0:
                    sys.exit("ERROR: unexpected recursive invocation of target")
                depth = 1
                invocations.append([])
            elif ev == "return":
                depth = 0
            elif ev == "line":
                if depth != 1:
                    sys.exit("ERROR: line event outside an invocation")
                invocations[-1].append(int(m.group("lineno")))

    if n_events == 0 or not invocations:
        sys.exit("ERROR: zero events for target function in trace")
    if len(invocations) < INVOCATION:
        sys.exit(f"ERROR: only {len(invocations)} invocations recorded")

    lines = invocations[INVOCATION - 1]
    count = sum(1 for ln in lines if ln == body_line)

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(oracle["oracle_answer"]))
    print(f"invocations={len(invocations)} line_events={len(lines)} body_line={body_line}")


if __name__ == "__main__":
    main()
