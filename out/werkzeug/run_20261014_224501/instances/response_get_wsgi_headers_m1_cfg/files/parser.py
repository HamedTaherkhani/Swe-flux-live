#!/usr/bin/env python
"""Trace -> oracle.json for response_get_wsgi_headers_m1_cfg (M1, line_execution_counts)."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET_REL = "src/werkzeug/wrappers/response.py"
TARGET_QUALNAME = "Response.get_wsgi_headers"
TEST_FILE = "werkzeug_qa/response_get_wsgi_headers_m1_cfg/files/testcase.py"
TEST_CLASS = "WsgiHeaderMatrixTest"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)


def target_span() -> tuple[int, int, int]:
    """Return (def_line, first_body_stmt_after_docstring_line, end_line)."""
    src = (ROOT / TARGET_REL).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Response":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name == "get_wsgi_headers":
                    body = node.body
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)
                    ):
                        body = body[1:]
                    return node.lineno, body[0].lineno, node.end_lineno
    raise SystemExit("ERROR: could not locate Response.get_wsgi_headers in source")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        print(f"ERROR: trace log missing or empty: {trace}", file=sys.stderr)
        return 1

    def_line, start, end = target_span()
    counts: Counter[int] = Counter()
    calls = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if not m.group("func").endswith("." + TARGET_QUALNAME):
            continue
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "line":
            counts[int(m.group("lineno"))] += 1

    if calls == 0 or not counts:
        print("ERROR: no call/line events for target in trace", file=sys.stderr)
        return 1
    outside = sorted(ln for ln in counts if ln < start or ln > end)
    if outside:
        print(f"ERROR: line events outside scope: {outside}", file=sys.stderr)
        return 1

    answer = {
        "line_execution_counts": [
            {"count": counts.get(ln, 0), "line": ln} for ln in range(start, end + 1)
        ]
    }

    question = (
        f"Run the pytest test class `{TEST_FILE}::{TEST_CLASS}` (file `{TEST_FILE}`, "
        f"class `{TEST_CLASS}`), i.e. ALL `test_*` methods of that class in one pytest "
        "session (pytest's default order, which is source order; the order does not affect "
        "the answer because counts are summed). During this run the method "
        f"`werkzeug.wrappers.response.{TARGET_QUALNAME}` (defined at `{TARGET_REL}:{def_line}`) "
        "is invoked indirectly, through the WSGI call chain `werkzeug.test.Client` -> the test's "
        "WSGI app -> `Response.__call__` -> `Response.get_wsgi_response`. An invocation is one "
        "call of that method; every invocation in every test method counts. "
        "Question: for EACH physical source line of that method from line "
        f"{start} through line {end} inclusive (the method body after its docstring; the `def` "
        f"line {def_line}, the decorator-free signature and the docstring lines are NOT in scope), "
        "how many times did that line execute in total, summed over all invocations in all test "
        "methods of the class? A line's count is the number of `'line'` events that CPython's "
        "`sys.settrace` line tracing (the interpreter in this repository's environment, Python "
        "3.11) reports for that line number while the frame of this method is executing; events "
        "from frames of other functions called by the method (e.g. `Headers` methods, "
        "`iri_to_uri`, `warnings.warn`, properties such as `is_sequence`) are not counted. "
        "Consequences of this definition that you must respect: a `for` header line is counted "
        "once per fetch of the next item, including the final fetch that exhausts the iterator "
        "(so a loop over 3 items contributes 4 to its header line); a multi-line statement "
        "usually fires its event on the line where the statement begins, but CPython may also "
        "fire extra events on continuation lines (e.g. a line holding a name lookup or an "
        "argument) and then again on the starting line, and every such event counts; "
        "`elif` conditions count on their own line only when they are evaluated. "
        "Lines that are blank, comments only, or never produce a line event (including "
        "continuation lines that emit no events) MUST still be listed, with count 0. "
        "Answer format: a JSON object with the single key `line_execution_counts`, whose value "
        "is a list containing exactly one object per line number in the range above (no gaps, "
        "no duplicates), each object having exactly the keys `line` (int, absolute 1-based line "
        f"number in `{TARGET_REL}` as it exists in the repository) and `count` (int, >= 0), "
        "sorted by `line` ascending."
    )

    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": question,
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calls={calls} line_events={sum(counts.values())} distinct={len(counts)}")
    print(json.dumps(answer["line_execution_counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
