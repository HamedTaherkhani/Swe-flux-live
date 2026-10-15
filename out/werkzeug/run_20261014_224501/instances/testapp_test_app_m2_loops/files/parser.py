#!/usr/bin/env python
"""Trace -> oracle.json for testapp_test_app_m2_loops (M2_Loops, total_iterations)."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/testapp.py"
TARGET_FUNC = "test_app"
TEST_PATH = "werkzeug_qa/testapp_test_app_m2_loops/files/testcase.py"
TEST_CLASS = "TestTestAppLoops"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def loop_info(source_path):
    tree = ast.parse(open(source_path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC:
            loops = [n for n in ast.walk(node) if isinstance(n, (ast.For, ast.While))]
            loops.sort(key=lambda n: n.lineno)
            return [(n.lineno, n.body[0].lineno) for n in loops]
    die("target function not found in source")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=os.getcwd())
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    loops = loop_info(os.path.join(args.root, TARGET_REL))
    if len(loops) != 3:
        die(f"expected 3 loops in {TARGET_FUNC}, found {len(loops)}")
    body_lines = {body: header for header, body in loops}

    calls = 0
    per_call = []
    events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m["file"].endswith(TARGET_REL):
                continue
            if m["func"].rpartition(".")[2] != TARGET_FUNC or "<locals>" in m["func"]:
                continue
            events += 1
            ev = m["event"]
            if ev == "call":
                calls += 1
                per_call.append({h: 0 for h, _ in loops})
            elif ev == "line":
                ln = int(m["line"])
                if ln in body_lines:
                    if not per_call:
                        die("line event before any call event")
                    per_call[-1][body_lines[ln]] += 1

    if events == 0 or calls == 0:
        die("no events for target function in trace")

    total = sum(sum(c.values()) for c in per_call)
    for i, c in enumerate(per_call, 1):
        print(f"invocation {i}: " + ", ".join(f"L{h}={c[h]}" for h in sorted(c)))
    print(f"invocations={calls} total={total}")

    h1, h2, h3 = (h for h, _ in loops)
    b1, b2, b3 = (b for _, b in loops)
    question = (
        f"Consider the test class `{TEST_CLASS}` in `{TEST_PATH}` (run with pytest from "
        f"the repository root; e.g. `pytest {TEST_PATH}::{TEST_CLASS}`). The answer aggregates "
        f"over ALL test methods in that class. During that run, the WSGI application function "
        f"`werkzeug.testapp.test_app` defined in `{TARGET_REL}` (the inner function decorated "
        f"with `@Request.application`, whose `def` is at line 125; the "
        f"`application` wrapper created by the decorator, the sort-key lambdas, and the "
        f"`iter_sys_path` generator are NOT part of it) is invoked a number of times. "
        f"An invocation is one call (one new frame) of that function, counted 1-based in "
        f"chronological order. The function contains three `for` loops, identified by their "
        f"header lines: line {h1} (`for egg in eggs:`), line {h2} "
        f"(`for key, value in sorted_environ:`) and line {h3} "
        f"(`for item, virtual, expanded in iter_sys_path():`). An iteration of a loop is one "
        f"execution of the first line of its body (line {b1}, line {b2} and line {b3} "
        f"respectively); a loop that is never entered or whose iterable is empty contributes 0 "
        f"iterations. Compute the total number of iterations of these three loops, summed over "
        f"all three loops and over every invocation of `test_app` during the whole test run "
        f"(all test methods of the class). Answer as a JSON object of the form "
        f'{{"total_iterations": <int>}}, where the value is a plain JSON integer (not a string).'
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": total},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    main()
