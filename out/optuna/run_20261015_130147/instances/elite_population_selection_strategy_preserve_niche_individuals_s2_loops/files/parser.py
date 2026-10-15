#!/usr/bin/env python
"""Derive the S2_Loops oracle for _preserve_niche_individuals from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/samplers/_nsgaiii/_elite_population_selection_strategy.py"
TARGET_QUALNAME = (
    "optuna.samplers._nsgaiii._elite_population_selection_strategy._preserve_niche_individuals"
)
FUNC_NAME = "_preserve_niche_individuals"
LOOP_HEADER_LINE = 288
INVOCATION = 1

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Consider the pytest test "
    "`optuna_qa/elite_population_selection_strategy_preserve_niche_individuals_s2_loops/files/"
    "testcase.py::TestPreserveNicheIndividuals::test_preserve_niche_selection` (test class "
    "`TestPreserveNicheIndividuals`, its single test method `test_preserve_niche_selection`). "
    "The test directly calls the function `_preserve_niche_individuals` (qualified name "
    "`optuna.samplers._nsgaiii._elite_population_selection_strategy._preserve_niche_individuals`) "
    "defined in the file `optuna/samplers/_nsgaiii/_elite_population_selection_strategy.py`. "
    "Invocations are counted 1-based, in chronological order of calls to this function during "
    "the test run. Look at the `while` loop whose header is at line 288 of that file (the "
    "statement `while len(additional_elite_population) < target_population_size:`), using "
    "absolute 1-based line numbers in the file as it exists in the repository. "
    "In the 1st invocation, how many iterations does this loop execute in total? An iteration "
    "is defined as one execution of the loop body's first line (line 289, "
    "`if len(nearest_points_count_to_reference_points[count]) == 0:`). Every pass through the "
    "body counts, INCLUDING passes that end at the `continue` statement on line 292 (i.e. passes "
    "that only increment `count` and shuffle, without selecting an individual); the final "
    "evaluation of the header condition that terminates the loop is not an iteration. "
    "Answer as a JSON object of the form {\"loop_iteration_count\": <int>} where the value is a "
    "plain JSON integer (not a string)."
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

    invocations = []
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
            elif ev == "line" and depth == 1:
                invocations[-1].append(int(m.group("lineno")))

    if n_events == 0:
        sys.exit("ERROR: zero trace events for target function")
    if len(invocations) < INVOCATION:
        sys.exit(f"ERROR: only {len(invocations)} invocations found")

    lines = invocations[INVOCATION - 1]
    count = sum(1 for ln in lines if ln == body_line)
    if count <= 0:
        sys.exit("ERROR: loop never iterated")

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
