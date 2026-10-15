#!/usr/bin/env python
"""Derive the S2_Loops oracle for StateMachineMatcher.match._match from a trace."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/werkzeug/routing/matcher.py"
QUALNAME_SUFFIX = "StateMachineMatcher.match.<locals>._match"
LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(src_path):
    """Return (header_line, first_body_line) of the `for test_part, new_state` loop."""
    tree = ast.parse(Path(src_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_match":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.For)
                    and isinstance(sub.iter, ast.Attribute)
                    and sub.iter.attr == "dynamic"
                ):
                    return sub.lineno, sub.body[0].lineno
    fail("could not locate the dynamic-transition loop in _match")


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
        if not m["file"].endswith(TARGET_REL) or not m["func"].endswith(QUALNAME_SUFFIX):
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
        "Consider the pytest test "
        "`werkzeug_qa/matcher_match_s2_loops/files/testcase.py::TestMatcherLoops::"
        "test_backtracking_dynamic_transitions` (test class `TestMatcherLoops`, its only "
        "test method). During this test, the nested function "
        "`werkzeug.routing.matcher.StateMachineMatcher.match.<locals>._match` defined in "
        f"`{TARGET_REL}` is invoked many times (recursively, once or twice per "
        "`StateMachineMatcher.match` call, since a retry with merged slashes may occur). "
        f"Focus on the `for test_part, new_state in state.dynamic:` loop whose header is at "
        f"line {header} of that file. Define one iteration of this loop as one execution "
        f"of the loop body's first line (line {body_first}, `target = part`). "
        "Count iterations in EVERY invocation of `_match` during the whole test run "
        "(an invocation = one call of `_match`, counting both the top-level calls made "
        "by `StateMachineMatcher.match` and all recursive calls, regardless of how the "
        "invocation ends: return of a value, return of None, or propagating "
        "`SlashRequired`), and sum them. An iteration of an outer frame's loop is not "
        "re-counted when a nested recursive invocation runs; each execution of line "
        f"{body_first} counts exactly once. Iterations that end early because the regex "
        "does not match, or that recurse and fail, still count. Answer with a JSON object "
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
