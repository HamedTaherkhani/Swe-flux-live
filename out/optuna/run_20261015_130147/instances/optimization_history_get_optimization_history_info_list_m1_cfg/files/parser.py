"""Harvest M1_IntraProceduralCFG oracle (per-line execution counts) for
_get_optimization_history_info_list from the trace log."""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "optuna/visualization/_optimization_history.py"
TARGET_NAME = "_get_optimization_history_info_list"
TARGET_FUNC = "optuna.visualization._optimization_history._get_optimization_history_info_list"
NESTED_FUNC = TARGET_FUNC + ".<locals>._aggregate"
COUNTED_FRAMES = {TARGET_FUNC, NESTED_FUNC}
TEST_PATH = "optuna_qa/optimization_history_get_optimization_history_info_list_m1_cfg/files/testcase.py"
TEST_CLASS = "TestOptimizationHistoryScenarios"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def target_scope(root):
    path = os.path.join(root, TARGET_FILE)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_NAME:
            return node.lineno, node.body[0].lineno, node.end_lineno
    fail(f"target function {TARGET_NAME} not found in {TARGET_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        fail("trace log is empty")

    def_line, first, last = target_scope(args.root)
    counts = {ln: 0 for ln in range(first, last + 1)}
    n_calls = 0
    n_events = 0
    for line in raw:
        m = LINE_RE.match(line)
        if not m or TARGET_FILE not in m.group("file"):
            continue
        func = m.group("func")
        if func not in COUNTED_FRAMES:
            continue
        n_events += 1
        event = m.group("event")
        lineno = int(m.group("lineno"))
        if event == "call" and func == TARGET_FUNC:
            n_calls += 1
        if event != "line":
            continue
        if lineno not in counts:
            fail(f"line event outside scope: {lineno}")
        counts[lineno] += 1
    if n_events == 0 or n_calls == 0:
        fail("no events for the target function in trace log")

    answer = {
        "line_execution_counts": [
            {"count": counts[ln], "line": ln} for ln in sorted(counts)
        ]
    }

    question = (
        f"Run the pytest test class `{TEST_PATH}::{TEST_CLASS}` (all of its test methods, "
        "i.e. every pytest id of the form "
        f"`{TEST_PATH}::{TEST_CLASS}::test_*`; the answer aggregates over ALL of them). "
        f"Consider the function `{TARGET_FUNC}` defined at `{TARGET_FILE}:{def_line}`. "
        f"For EVERY physical line number L from {first} (the first line of the function body) "
        f"through {last} (the last line of the function) inclusive, report how many times "
        "line L was executed in total over the whole test-class run, summed across all "
        "invocations of the function in all test methods.\n\n"
        "Definition of an execution: one CPython `sys.settrace` 'line' event (Python 3.11, "
        "as installed in the repository environment) whose frame is either (a) a frame "
        f"executing `{TARGET_FUNC}` itself, or (b) a frame executing its nested function "
        f"`{NESTED_FUNC}` (the inner `_aggregate` helper defined inside it). Line events "
        "fired in any other frame are NOT counted: in particular list comprehensions and "
        "generator expressions run in their own separate frames in Python 3.11 "
        "(`<listcomp>`, `<genexpr>`), so their per-element iterations do not add to the "
        "count of any line; nor do callees such as `_check_plot_args`, `Study.get_trials`, "
        "the `target` callable, numpy, or logging. Only 'line' events count; 'call', "
        "'return' and 'exception' events do not. Every line event counts, including repeated "
        "line events that CPython fires for the same line within a single statement execution "
        "(e.g. a `for` header line fires once per iteration plus once more when the iterator "
        "is exhausted, and a multi-line statement may fire events on its first line and on "
        "some continuation lines, possibly returning to the first line) — report exactly what "
        "the interpreter's line events produce, attributed to the line number reported by "
        "`frame.f_lineno` at the event. The outer `def` line and its signature lines "
        f"(lines {def_line}-{first - 1}) are outside the scope and must not be reported. The "
        "nested `def _aggregate(...)` line is inside the scope and counts each time the outer "
        "frame executes that definition statement (the nested function's own 'call' event "
        "does not count). Blank lines, comment-only lines, and lines that never fire a line "
        "event (continuation lines, never-taken branches, etc.) are still reported, with "
        "count 0.\n\n"
        "Answer format: a JSON object with a single key `line_execution_counts` whose value "
        "is a list with exactly one object per line number in the range above, each object "
        "having exactly two keys: `line` (int, absolute 1-based line number in "
        f"`{TARGET_FILE}` as it exists in the repository) and `count` (int, total number of "
        "line events, 0 if none). Sort the list by `line` ascending; there are no duplicate "
        "line numbers."
    )

    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": question,
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
