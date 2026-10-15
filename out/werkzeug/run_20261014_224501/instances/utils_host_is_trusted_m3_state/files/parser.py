#!/usr/bin/env python
"""Trace -> oracle for utils_host_is_trusted_m3_state.

Collects every distinct value (repr) bound to the local variable ``ref``
inside ``host_is_trusted`` across all invocations.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_SUFFIX = "werkzeug.sansio.utils.host_is_trusted"
TARGET_FILE = "src/werkzeug/sansio/utils.py"
VARIABLE = "ref"

LINE_RE = re.compile(r"^\S+ \S+ (?P<path>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) ")

QUESTION = (
    "Consider the test class `HostIsTrustedStateTest` in "
    "`werkzeug_qa/utils_host_is_trusted_m3_state/files/testcase.py`. Run ALL of its "
    "test methods with pytest (pytest id "
    "`werkzeug_qa/utils_host_is_trusted_m3_state/files/testcase.py::HostIsTrustedStateTest`); "
    "the answer aggregates over every test method in the class. "
    "The target function is `werkzeug.sansio.utils.host_is_trusted` in "
    "`src/werkzeug/sansio/utils.py` (lines 25-82), which the test calls directly. "
    "Aggregate over ALL invocations of this function during the run (an invocation is "
    "one call of the function; invocations that return early, before the loop, or that "
    "end by propagating an exception all count). "
    "Collect every value that the local variable `ref` is ever bound to inside the "
    "function's own frame: this includes each binding by the `for ref in trusted_list:` "
    "loop header, the rebinding `ref = ref[1:]`, and the rebinding "
    "`ref = ref.encode(\"idna\").decode(\"ascii\")` (only if that right-hand side "
    "completes; if it raises, no new value is bound). Values from different invocations "
    "and different test methods are pooled together. Report each distinct value as its "
    "Python 3 `repr()` string (Python's default str repr: single-quoted, e.g. the str "
    "abc.xy is written as \"'abc.xy'\"; printable non-ASCII characters appear literally, "
    "non-printable characters appear as backslash escapes such as `\\u200b`). Remove "
    "duplicates (two values are duplicates iff their repr strings are equal) and sort "
    "the repr strings ascending by plain Python string comparison (Unicode code-point "
    "order of the full repr string, including the leading quote). "
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
        fail("no events for host_is_trusted in trace")
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
    print(json.dumps(oracle["oracle_answer"], indent=2, ensure_ascii=False))
    print(f"invocations={n_calls} events={n_events}")


if __name__ == "__main__":
    main()
