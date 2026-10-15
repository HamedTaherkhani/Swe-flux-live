#!/usr/bin/env python
"""Derive the S2_Loops oracle for werkzeug.debug.tbtools._process_traceback."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/werkzeug/debug/tbtools.py"
QUALNAME = "werkzeug.debug.tbtools._process_traceback"
TEST_ID = (
    "werkzeug_qa/tbtools_process_traceback_s2_loops/files/testcase.py::"
    "TestProcessTracebackLoops::test_chained_collatz_traceback"
)
LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(src_path):
    """Return (header_line, first_body_line) of the frame-matching `for` loop."""
    tree = ast.parse(Path(src_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_traceback":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.For)
                    and isinstance(sub.iter, ast.Call)
                    and isinstance(sub.iter.func, ast.Name)
                    and sub.iter.func.id == "zip"
                ):
                    return sub.lineno, sub.body[0].lineno
    fail("could not locate the zip(frame_gen, te.stack) loop in _process_traceback")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path(__file__).resolve().parents[3] / TARGET_REL
    if not src.is_file():
        src = Path("/testbed") / TARGET_REL
    header, body_first = find_loop(src)

    calls = 0
    body_hits = 0
    line_events = 0
    for raw in trace.read_text().splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m["file"].endswith(TARGET_REL) or m["func"] != QUALNAME:
            continue
        ev = m["event"]
        if ev == "call":
            calls += 1
        elif ev == "line":
            line_events += 1
            if int(m["line"]) == body_first:
                body_hits += 1
    if calls == 0 or line_events == 0:
        fail("trace contains zero events for the target function")

    question = (
        f"Consider the pytest test `{TEST_ID}` (test class `TestProcessTracebackLoops` "
        "in `werkzeug_qa/tbtools_process_traceback_s2_loops/files/testcase.py`, its only "
        "test method). The test calls the module-level function "
        f"`werkzeug.debug.tbtools._process_traceback` defined in `{TARGET_REL}` once "
        "directly; that function then calls itself recursively for the `__context__` "
        "and `__cause__` entries of the `traceback.TracebackException` it processes. "
        "An invocation is one `call` of `_process_traceback` during the test run "
        "(the direct call plus every recursive call). "
        f"Focus on the loop `for (f, _), fs in zip(frame_gen, te.stack, strict=True):` "
        f"whose header is at line {header} of that file (absolute, 1-based line numbers "
        "of the file as it exists in the repository). Define one iteration of this loop as "
        f"one execution of the loop body's first line (line {body_first}, `if hide:`). "
        "An iteration counts even if it later hits `continue` and does not append a "
        "frame. Count the iterations across ALL invocations of `_process_traceback` "
        "during the test (each execution of that line counts exactly once; iterations "
        "of a caller invocation are not re-counted when a nested recursive invocation "
        "runs) and report the total. Answer with a JSON object "
        "`{\"loop_iteration_count\": <int>}` where the value is a plain JSON integer "
        "(not a string)."
    )
    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": body_hits},
    }
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(f"invocations={calls} line_events={line_events}")


if __name__ == "__main__":
    main()
