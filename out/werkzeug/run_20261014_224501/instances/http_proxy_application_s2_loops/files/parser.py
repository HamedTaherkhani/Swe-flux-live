#!/usr/bin/env python
"""Derive the S2_Loops oracle for ProxyMiddleware.proxy_to.<locals>.application."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/werkzeug/middleware/http_proxy.py"
QUALNAME_SUFFIX = "ProxyMiddleware.proxy_to.<locals>.application"
TARGET_INVOCATION = 2
LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(src_path):
    """Return (header_line, first_body_line) of `for k, v in headers.items():`."""
    tree = ast.parse(Path(src_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "proxy_to":
            for fn in ast.walk(node):
                if isinstance(fn, ast.FunctionDef) and fn.name == "application":
                    for sub in ast.walk(fn):
                        if (
                            isinstance(sub, ast.For)
                            and isinstance(sub.iter, ast.Call)
                            and isinstance(sub.iter.func, ast.Attribute)
                            and sub.iter.func.attr == "items"
                            and isinstance(sub.iter.func.value, ast.Name)
                            and sub.iter.func.value.id == "headers"
                        ):
                            return sub.lineno, sub.body[0].lineno
    fail("could not locate the header-forwarding loop in application")


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
    line_events = 0
    per_invocation = {}
    for raw in trace.read_text().splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m["file"].endswith(TARGET_REL) or not m["func"].endswith(QUALNAME_SUFFIX):
            continue
        ev = m["event"]
        if ev == "call":
            calls += 1
            per_invocation[calls] = 0
        elif ev == "line":
            if calls == 0:
                fail("line event before any call event")
            line_events += 1
            if int(m["line"]) == body_first:
                per_invocation[calls] += 1
    if calls == 0 or line_events == 0:
        fail("trace contains zero events for the target function")
    if calls < TARGET_INVOCATION:
        fail(f"only {calls} invocations traced; need invocation {TARGET_INVOCATION}")
    count = per_invocation[TARGET_INVOCATION]

    test_id = (
        "werkzeug_qa/http_proxy_application_s2_loops/files/testcase.py::"
        "TestProxyApplicationLoops::test_header_and_body_forwarding"
    )
    question = (
        f"Consider the pytest test `{test_id}` (test class `TestProxyApplicationLoops`, "
        "its only test method `test_header_and_body_forwarding`). The test calls "
        "`ProxyMiddleware.proxy_to` several times and invokes each returned WSGI app. "
        "The target is the nested function `application` defined inside "
        "`ProxyMiddleware.proxy_to` in "
        f"`{TARGET_REL}` (qualname `werkzeug.middleware.http_proxy.ProxyMiddleware."
        "proxy_to.<locals>.application`, i.e. the undecorated function body that the "
        "`@Request.application` decorator wraps, not the decorator's own wrapper in "
        "`src/werkzeug/wrappers/request.py`). An invocation is one call of that nested "
        "function's body during the test run, counted 1-based in chronological order. "
        f"Focus on the `for k, v in headers.items():` loop whose header is at line {header} "
        f"of that file. Define one iteration as one execution of the loop body's first line "
        f"(line {body_first}, `con.putheader(k, v)`). How many iterations does this loop "
        f"perform during invocation number {TARGET_INVOCATION} (the second invocation)? "
        "Count only that one invocation (do not sum across invocations). Answer with a JSON "
        "object `{\"loop_iteration_count\": <int>}` where the value is a plain JSON integer "
        "(not a string), e.g. `{\"loop_iteration_count\": 3}`."
    )
    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(
        f"invocations={calls} line_events={line_events} "
        f"per_invocation={sorted(per_invocation.items())}"
    )


if __name__ == "__main__":
    main()
