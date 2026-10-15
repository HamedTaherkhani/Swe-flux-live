#!/usr/bin/env python
"""Derive the S1_IntraProceduralCFG oracle for SuccessiveHalvingPruner.prune.

Line events of the chosen invocation are mapped to the first line of the statement being
executed (for `if`/`while`, the header line) and consecutive events belonging to the same
statement execution are collapsed into one element.
"""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/pruners/_successive_halving.py"
TARGET_QUALNAME = "optuna.pruners._successive_halving.SuccessiveHalvingPruner.prune"
TEST_FILE = "optuna_qa/successive_halving_prune_s1_cfg/files/testcase.py"
TEST_CLASS = "TestSuccessiveHalvingPruneScenario"
TEST_METHOD = "test_prune_sequence"
INVOCATION = 46

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test `" + TEST_FILE + "::" + TEST_CLASS + "::" + TEST_METHOD + "` "
    "(test class `" + TEST_CLASS + "`, single test method `" + TEST_METHOD + "`, file `"
    + TEST_FILE + "`). During this test the method `SuccessiveHalvingPruner.prune` defined in "
    "`" + TARGET_REL + "` (dotted qualname `" + TARGET_QUALNAME + "`) is called directly by the "
    "test many times. Invocations are counted 1-based in chronological order of the calls to "
    "this method during the test run (every call counts, whatever it returns).\n\n"
    "Question: for invocation number " + str(INVOCATION) + ", give the exact ordered sequence "
    "of source lines executed inside the body of `prune` (only lines of `prune` itself, in its "
    "own frame; lines executed inside functions it calls, such as `_get_current_rung`, "
    "`_estimate_min_resource`, `_get_competing_values`, `_is_trial_promotable_to_next_rung`, "
    "`study.get_trials` or the storage, are NOT included).\n\n"
    "Counting rules:\n"
    "- Each execution of a statement contributes exactly ONE element, whose `line` is the "
    "absolute 1-based line number (in `" + TARGET_REL + "` as it exists in the repository) on "
    "which that statement begins. For an `if` or `while` statement this is the line holding "
    "the `if`/`while` keyword; evaluating its condition is that one element (the body "
    "statements are separate elements). A statement or condition spanning several physical "
    "lines is reported once, at its first line, even though evaluation touches the "
    "continuation lines. This function contains two such constructs: the multi-line "
    "assignment `rung_promotion_step = self._min_resource * (...)` and the multi-line "
    "condition `if not _is_trial_promotable_to_next_rung(...):`; each counts as a single "
    "element at its first line per execution.\n"
    "- The `def prune(...)` line never appears (nor any decorator/docstring line). Comments and "
    "blank lines never appear.\n"
    "- The `while True:` header appears once when the loop is first entered and once more each "
    "time control loops back to it after the last statement of the loop body.\n"
    "- `return` statements appear as an element (at the line of the `return`) when executed; "
    "the invocation ends there. `assert` statements appear when executed.\n"
    "- The sequence is in execution order, with no deduplication: a line executed several "
    "times appears several times.\n\n"
    "Answer format: a JSON object `{\"executed_path\": [...]}` where each element is an object "
    "with exactly the keys `file` (string, the repo-relative path `" + TARGET_REL + "`), `func` "
    "(string, the dotted `module.qualname` `" + TARGET_QUALNAME + "`) and `line` (JSON "
    "integer). `file` and `func` are identical in every element."
)

TEMPLATE = {"executed_path": [{"file": "str", "func": "str", "line": "int"}]}


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def statement_start_map(src_path: str) -> dict:
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SuccessiveHalvingPruner":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "prune":
                    func = item
    if func is None:
        die("could not locate SuccessiveHalvingPruner.prune in source")
    mapping = {}
    spans = []
    for node in ast.walk(func):
        if not isinstance(node, ast.stmt) or node is func:
            continue
        if isinstance(node, (ast.If, ast.While)):
            end = node.test.end_lineno
        elif hasattr(node, "body"):
            end = node.lineno
        else:
            end = node.end_lineno
        spans.append((node.lineno, end))
    for start, end in sorted(spans):
        for ln in range(start, end + 1):
            # Innermost (latest-starting) statement owning the line wins.
            if ln not in mapping or mapping[ln] < start:
                mapping[ln] = start
    return mapping


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        die(f"trace log empty: {args.trace_log}")

    src_path = os.path.join(os.getcwd(), TARGET_REL)
    if not os.path.isfile(src_path):
        die(f"target source missing: {src_path}")
    stmt_start = statement_start_map(src_path)

    invocations = []
    current = None
    n_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            if m.group("func") != TARGET_QUALNAME:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
                continue
            n_events += 1
            event = m.group("event")
            lineno = int(m.group("lineno"))
            if event == "call":
                current = []
                invocations.append(current)
            elif event == "line":
                if current is None:
                    die("line event outside of an invocation")
                current.append(lineno)
            elif event == "return":
                current = None

    if n_events == 0 or not invocations:
        die("no events for target function in trace")
    if len(invocations) < INVOCATION:
        die(f"only {len(invocations)} invocations recorded; need {INVOCATION}")

    lines = invocations[INVOCATION - 1]
    if not lines:
        die("selected invocation has no line events")
    path = []
    prev = None
    for ln in lines:
        if ln not in stmt_start:
            die(f"line {ln} not inside a statement of prune")
        start = stmt_start[ln]
        if start == prev:
            # Continuation line (or re-touched first line) of the multi-line statement
            # currently executing; no statement of prune can run twice back to back.
            continue
        path.append(start)
        prev = start

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_REL, "func": TARGET_QUALNAME, "line": ln} for ln in path
            ]
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={len(invocations)} selected={INVOCATION} path_len={len(path)}")
    print("path=" + ",".join(str(x) for x in path))


if __name__ == "__main__":
    main()
