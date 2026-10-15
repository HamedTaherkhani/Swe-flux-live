#!/usr/bin/env python
"""Harvest per-invocation iteration counts of the innermost `for name in files`
loop of werkzeug._reloader._find_stat_paths from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/_reloader.py"
FUNC = "werkzeug._reloader._find_stat_paths"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop_lines(src_path):
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_find_stat_paths"),
        None,
    )
    if fn is None:
        die("target function not found in source")
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
    inner = [
        n for n in loops
        if isinstance(n.target, ast.Name) and n.target.id == "name"
        and isinstance(n.iter, ast.Name) and n.iter.id == "files"
    ]
    if len(inner) != 1:
        die("could not uniquely identify `for name in files` loop")
    return inner[0].lineno, inner[0].body[0].lineno


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    src = os.path.join(root, TARGET_REL)
    if not os.path.isfile(src):
        src = os.path.join(os.getcwd(), TARGET_REL)
    header, body_first = find_loop_lines(src)

    counts = []
    events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m["file"].replace("\\", "/").endswith(TARGET_REL) or not (
                m["func"] == FUNC or m["func"].endswith("._find_stat_paths")
            ):
                continue
            events += 1
            ev = m["event"]
            if ev == "call":
                counts.append(0)
            elif ev == "line" and int(m["lineno"]) == body_first:
                if not counts:
                    die("line event before any call event")
                counts[-1] += 1

    if events == 0 or not counts:
        die("no events for target function in trace")

    print(f"loop header line {header}, body first line {body_first}")
    print(f"invocations={len(counts)} per-invocation counts={counts}")

    question = (
        "Run every test method of the unittest class `FindStatPathsLoopTest` in "
        "`werkzeug_qa/reloader_find_stat_paths_m2_loops/files/testcase.py` (all 12 `test_*` "
        "methods, e.g. `pytest werkzeug_qa/reloader_find_stat_paths_m2_loops/files/testcase.py::FindStatPathsLoopTest`). "
        "The tests never call the target directly; they reach it through "
        "`StatReloaderLoop.__enter__` / `StatReloaderLoop.run_step`. "
        "Target: the function `werkzeug._reloader._find_stat_paths` in `src/werkzeug/_reloader.py`. "
        f"Consider the innermost loop `for name in files:` whose header is on line {header} "
        "(nested inside the `for root, dirs, files in os.walk(path):` loop, which is itself inside "
        "the `for path in chain(list(sys.path), extra_files):` loop). "
        f"One iteration of this loop = one execution of its body's first line (line {body_first}, "
        "`if name.endswith((\".py\", \".pyc\")):`), counted 1-based. "
        "An invocation = one call of `_find_stat_paths` during the whole test run (all test methods together, "
        "every call counts, including repeated `run_step` calls within one test). "
        "For each invocation, sum the iterations of this loop over ALL the times the loop is entered "
        "during that invocation (i.e. over every directory visited by every `os.walk` in that call); "
        "an invocation in which the loop body never runs has count 0 and is included. "
        "Report `max_iterations` = the largest such per-invocation total and `min_iterations` = the smallest, "
        "taken over all invocations of the test run. Both are plain JSON integers."
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {"max_iterations": max(counts), "min_iterations": min(counts)},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"]))


if __name__ == "__main__":
    main()
