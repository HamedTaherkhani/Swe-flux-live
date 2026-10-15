#!/usr/bin/env python
"""Trace -> oracle.json for wilcoxon_prune_m1_cfg (per-line execution counts)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys


TARGET_REL = "optuna/pruners/_wilcoxon.py"
TARGET_QUALNAME = "optuna.pruners._wilcoxon.WilcoxonPruner.prune"
TEST_PATH = "optuna_qa/wilcoxon_prune_m1_cfg/files/testcase.py"
TEST_CLASS = "TestWilcoxonPruneScenarios"

EVENT_RE = re.compile(r"^\S+ \S+ (\S+):(\d+) (\S+) event=(\w+)")


def _find_function_span(src_path: str) -> tuple[int, int]:
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WilcoxonPruner":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "prune":
                    return item.lineno, item.end_lineno
    raise SystemExit("ERROR: could not locate WilcoxonPruner.prune in source")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    repo_root = os.getcwd()
    src_path = os.path.join(repo_root, TARGET_REL)
    def_line, end_line = _find_function_span(src_path)
    first_body, last_body = def_line + 1, end_line

    counts = {ln: 0 for ln in range(first_body, last_body + 1)}
    n_calls = 0
    n_target_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.match(raw)
            if not m:
                continue
            path, lineno, func, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if not path.replace("\\", "/").endswith(TARGET_REL) or func != TARGET_QUALNAME:
                continue
            n_target_events += 1
            if event == "call":
                n_calls += 1
            elif event == "line":
                if lineno not in counts:
                    sys.exit(f"ERROR: line event outside function span: {lineno}")
                counts[lineno] += 1

    if n_target_events == 0 or n_calls == 0:
        sys.exit("ERROR: no events for the target function in the trace log")

    answer = {
        "line_execution_counts": [
            {"count": counts[ln], "line": ln} for ln in sorted(counts)
        ]
    }

    question = (
        f"Run the pytest test class `{TEST_PATH}::{TEST_CLASS}` (all of its test methods, "
        f"i.e. every pytest id of the form `{TEST_PATH}::{TEST_CLASS}::test_*`) in the "
        f"repository as checked out. During that run, the method "
        f"`{TARGET_QUALNAME}` (defined in `{TARGET_REL}`, `def prune` on line {def_line}, "
        f"body ending on line {last_body}) is invoked many times. "
        f"For EVERY physical line number L from {first_body} to {last_body} inclusive "
        f"(the def line {def_line} itself and any decorators are excluded; blank lines, "
        "comment-only lines, and continuation lines of multi-line statements are NOT "
        "excluded and simply appear with whatever count they get, typically 0), report "
        "how many times line L was executed in total. "
        "\"Executed\" is defined precisely as: the number of `line` events that CPython's "
        "`sys.settrace` line tracing (the interpreter used to run this repository's tests) "
        "reports with `frame.f_lineno == L` for frames whose code object is "
        "`WilcoxonPruner.prune` in that file. `call`, `return`, and `exception` events are "
        "NOT counted, and lines of other functions called from `prune` (e.g. inside scipy, "
        "numpy, `Study.best_trial`, `optuna_warn`) are NOT counted. Note that a "
        "multi-line statement may produce line events on more than one of its physical "
        "lines (whatever the interpreter actually reports is what counts), and a line "
        "re-entered in the same invocation counts each time. "
        "Counts are TOTALS summed over all invocations of `prune` in all test methods "
        "of the class (including any made during setUp/tearDown, though none are "
        "expected); lines never executed must still be listed with count 0. "
        "Answer as a JSON object with exactly one key `line_execution_counts`, whose value is "
        "a list of objects with exactly the keys `line` (int, absolute 1-based line number "
        f"in `{TARGET_REL}`) and `count` (int, >= 0). The list must contain exactly one "
        f"entry per line number from {first_body} to {last_body} (no duplicates, none "
        "omitted), sorted by `line` ascending. Example of the format (values illustrative "
        "only): {\"line_execution_counts\": [{\"count\": 3, \"line\": 1000}, "
        "{\"count\": 0, \"line\": 1001}]}."
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
    nonzero = sum(1 for v in counts.values() if v)
    total = sum(counts.values())
    print(f"calls={n_calls} line_events={total} distinct_lines={nonzero}")


if __name__ == "__main__":
    main()
