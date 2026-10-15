#!/usr/bin/env python
"""Derive the executed line path of werkzeug.utils.send_file (8th call) from the trace."""
import argparse
import json
import os
import re
import sys

TARGET_FILE_REL = "src/werkzeug/utils.py"
TARGET_FUNC = "werkzeug.utils.send_file"
INVOCATION = 8

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Run the pytest test "
    "`werkzeug_qa/utils_send_file_s1_cfg/files/testcase.py::SendFromDirectoryMatrixTest::test_matrix` "
    "(test class `SendFromDirectoryMatrixTest`, single test method `test_matrix`). During this test, "
    "the function `send_file` defined in `src/werkzeug/utils.py` (module-qualified name "
    "`werkzeug.utils.send_file`) is reached only indirectly, via `werkzeug.utils.send_from_directory`. "
    "Count invocations of `send_file` as the 1-based chronological order in which a new frame of "
    "`werkzeug.utils.send_file` is entered (i.e. `call` events) during the test; calls of "
    "`send_from_directory` that raise before calling `send_file` do not count. "
    "For the 8th invocation, report the exact ordered sequence of executed source lines inside that "
    "`send_file` frame, defined as exactly the sequence of `'line'` events that CPython's `sys.settrace` "
    "(the Python used to run the repository's tests in this environment) delivers for that frame, from "
    "its `call` event until the frame is exited (normally or by an exception). Rules: the `def` line, "
    "decorator lines and docstring lines are NOT included (no line event is delivered for them); do not "
    "include `call`, `return` or `exception` events themselves, only `line` events; do not include lines "
    "executed in any other frame (callees such as `Response.__init__`, `wrap_file`, `apply_range`, "
    "`max_age` callables, etc. are excluded); keep duplicates and repeated lines exactly in the order "
    "the events occur. Note that `send_file` contains multi-line statements (e.g. the multi-line "
    "`response_class(...)` call and multi-line `headers.set`/`raise` statements): report each line "
    "number exactly as the line event reports it -- normally the line where a statement begins, but if "
    "the interpreter delivers line events for continuation lines of a multi-line call (e.g. one per "
    "argument line) and then re-delivers the statement's first line, include all of those events, in "
    "order. Line numbers are absolute, 1-based line numbers in `src/werkzeug/utils.py` as it exists in "
    "the repository. Answer as a JSON object `{\"executed_path\": [...]}` whose list elements are "
    "objects `{\"file\": str, \"func\": str, \"line\": int}` in event order, where `file` is always the "
    "repo-relative path `src/werkzeug/utils.py` and `func` is always the dotted module.qualname "
    "`werkzeug.utils.send_file` (both identical in every element), and `line` is a JSON integer."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    invocations = []
    current = None
    depth_stack = []
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            if m["func"] != TARGET_FUNC or not m["file"].endswith(TARGET_FILE_REL):
                continue
            ev = m["event"]
            if ev == "call":
                if current is not None:
                    sys.exit("ERROR: unexpected nested/recursive send_file frame")
                current = []
                invocations.append(current)
            elif ev == "line":
                if current is None:
                    sys.exit("ERROR: line event outside a send_file frame")
                current.append(int(m["line"]))
            elif ev == "return":
                current = None

    if not invocations:
        sys.exit("ERROR: zero send_file invocations found in trace")
    if len(invocations) < INVOCATION:
        sys.exit(f"ERROR: only {len(invocations)} invocations, need {INVOCATION}")

    path = invocations[INVOCATION - 1]
    if not path:
        sys.exit("ERROR: target invocation has no line events")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_FILE_REL, "func": TARGET_FUNC, "line": ln} for ln in path
            ]
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"invocations={len(invocations)} target={INVOCATION} path_len={len(path)}")
    print(f"distinct_lines={len(set(path))}")


if __name__ == "__main__":
    main()
