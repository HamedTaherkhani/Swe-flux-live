#!/usr/bin/env python
"""Trace -> oracle for formparser_parse_m3_state.

Collects every distinct value (repr) bound to the local variable
``field_size`` inside ``MultiPartParser.parse`` across all invocations.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_SUFFIX = ".MultiPartParser.parse"
TARGET_FILE = "src/werkzeug/formparser.py"
VARIABLE = "field_size"

LINE_RE = re.compile(r"^\S+ \S+ (?P<path>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) ")

QUESTION = (
    "Consider the test class `MultipartStateTest` in "
    "`werkzeug_qa/formparser_parse_m3_state/files/testcase.py` (run all of its "
    "test methods with pytest, e.g. pytest id "
    "`werkzeug_qa/formparser_parse_m3_state/files/testcase.py::MultipartStateTest`). "
    "The test never calls the target directly; it builds multipart/form-data request "
    "bodies and parses them through werkzeug's form-data parsing entry point. "
    "The target function is `werkzeug.formparser.MultiPartParser.parse` in "
    "`src/werkzeug/formparser.py`. Aggregate over ALL invocations of this function "
    "during the run of ALL test methods in the class (an invocation is one call of "
    "the function; invocations that end by raising an exception count too). "
    "Collect every value that the local variable `field_size` is ever bound to inside "
    "the function's own frame: this includes its initial annotated assignment, the "
    "resets when a new part starts, and every update by the augmented assignment "
    "`field_size += ...` (the value after the update counts, including an update that "
    "is immediately followed by a raise). Values from different invocations are "
    "pooled together. Report each distinct value as its Python `repr()` string (an "
    "int such as 7 is written as \"7\"; Python's None is written as \"None\", not "
    "JSON null). Remove duplicates and sort the strings ascending by plain "
    "lexicographic Python string comparison (code-point order, so e.g. \"105\" sorts "
    "before \"23\", and \"None\" sorts after all digit strings). "
    "Answer as JSON of the form {\"unique_values\": [\"...\", ...]}."
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_locals(line: str) -> dict:
    idx = line.rfind(" locals={")
    if idx < 0:
        return {}
    raw = line[idx + len(" locals="):].strip()
    try:
        value = ast.literal_eval(raw)
    except Exception as exc:  # pragma: no cover - defensive
        fail(f"cannot parse locals: {exc}: {raw[:200]}")
    return value if isinstance(value, dict) else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        fail("trace log is empty")

    values: set[str] = set()
    n_events = 0
    n_calls = 0
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("path").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        n_events += 1
        if m.group("event") == "call":
            n_calls += 1
        loc = parse_locals(line)
        if VARIABLE in loc:
            values.add(loc[VARIABLE])

    if n_events == 0 or n_calls == 0:
        fail("no events for MultiPartParser.parse in trace")
    if not values:
        fail(f"variable {VARIABLE} never observed")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    print(f"invocations={n_calls} events={n_events}")


if __name__ == "__main__":
    main()
