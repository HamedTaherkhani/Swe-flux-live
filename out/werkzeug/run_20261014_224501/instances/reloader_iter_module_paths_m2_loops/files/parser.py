#!/usr/bin/env python
"""Trace -> oracle.json for reloader_iter_module_paths_m2_loops."""

import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/_reloader.py"
FUNC_NAME = "_iter_module_paths"
QUALNAME = "werkzeug._reloader._iter_module_paths"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: (?:retval|exc)=.*?)? locals=(?P<locals>.*)$"
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def loop_lines(source_path):
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            fors = [n for n in ast.walk(node) if isinstance(n, ast.For)]
            whiles = [n for n in ast.walk(node) if isinstance(n, ast.While)]
            if len(fors) != 1 or len(whiles) != 1:
                die("unexpected loop structure in target")
            return whiles[0].lineno, whiles[0].body[0].lineno
    die(f"{FUNC_NAME} not found in {source_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    root = os.getcwd()
    src = os.path.join(root, TARGET_REL)
    while_header, while_body = loop_lines(src)

    counts = []  # per invocation (generator lifetime) while-body executions
    events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            if not m.group("file").endswith(TARGET_REL):
                continue
            if m.group("func") != QUALNAME:
                continue
            events += 1
            ev = m.group("event")
            if ev == "call":
                # A fresh generator start has no locals yet; a resumption after
                # ``yield`` carries the frame's existing locals.
                if m.group("locals") == "{}":
                    counts.append(0)
                elif not counts:
                    die("resumption seen before any fresh invocation")
            elif ev == "line" and int(m.group("line")) == while_body:
                if not counts:
                    die("loop line before any invocation")
                counts[-1] += 1

    if events == 0 or not counts:
        die("no events for target function in trace")

    question = (
        "Run every test method of the unittest class `IterModulePathsLoopTest` in "
        "`werkzeug_qa/reloader_iter_module_paths_m2_loops/files/testcase.py` "
        "(i.e. the whole class, pytest id prefix "
        "`werkzeug_qa/reloader_iter_module_paths_m2_loops/files/testcase.py::IterModulePathsLoopTest`), "
        "with pytest launched from the repository root as the working directory. "
        "The answer aggregates over ALL test methods in the class. "
        "Consider the generator function `werkzeug._reloader._iter_module_paths` defined in "
        f"`{TARGET_REL}`. It contains an outer `for` loop over the module objects and, nested "
        f"inside it, a `while` loop whose header is on line {while_header} "
        "(`while not os.path.isfile(name):`). Define an invocation as one generator object "
        "created by calling `_iter_module_paths()` during the run (counted in chronological "
        "order, 1-based); suspending at `yield` and later resuming the same generator belongs to "
        "the SAME invocation, it is not a new one. Define one iteration of the `while` loop as one "
        f"execution of its body's first statement, `old = name` on line {while_body}; the "
        "`while` loop's iterations are summed over all outer `for`-loop iterations within one "
        "invocation (an iteration that ends via `break` still counts; a `while` that never "
        "enters its body contributes 0). Every invocation during the run counts, including ones "
        "that occur in `__enter__` of the reloader loop, in later `run_step()` calls, and via "
        "`_find_watchdog_paths`, even if that invocation yields nothing. "
        "Report `max_iterations`: the largest per-invocation `while`-iteration total over all "
        "invocations, and `min_iterations`: the smallest such total (both plain JSON integers). "
        'Answer as JSON exactly of the form {"max_iterations": <int>, "min_iterations": <int>}.'
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {"max_iterations": max(counts), "min_iterations": min(counts)},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print("per-invocation counts:", counts, file=sys.stderr)


if __name__ == "__main__":
    main()
