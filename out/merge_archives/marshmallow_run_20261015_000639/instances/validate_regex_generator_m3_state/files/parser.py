#!/usr/bin/env python
"""Parse the trace log into the M3_ProgramState oracle for URL.RegexMemoizer._regex_generator."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE_REL = "src/marshmallow/validate.py"
TARGET_SUFFIX = "URL.RegexMemoizer._regex_generator"
VARIABLE = "hostname_variants"
TRACE_REPR_LIMIT = 500
TEST_FILE = "marshmallow_qa/validate_regex_generator_m3_state/files/testcase.py"
TEST_CLASS = "RegexGeneratorStateTest"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = f"""\
Test: `{TEST_FILE}`, test class `{TEST_CLASS}`. Run the WHOLE class with pytest from the repository root \
(pytest id `{TEST_FILE}::{TEST_CLASS}`); it contains 12 `test_...` methods and the answer aggregates over ALL of \
them (the answer is a set, so the order in which the methods run does not matter).

Target function: `URL.RegexMemoizer._regex_generator` defined in `{TARGET_FILE_REL}` (nested class \
`RegexMemoizer` inside class `URL`; module `marshmallow.validate`). The tests call it directly, each time on a \
fresh `RegexMemoizer` instance and with the module global `_UNICODE_LETTERS` temporarily patched to a \
test-computed string.

An invocation is one call of the target (one new frame of `_regex_generator`) during the test run. Inside each \
invocation, the local variable `{VARIABLE}` is first bound to a list and that same list object may later be \
mutated in place (an element appended) before the function returns.

Question: across every invocation in every test method, consider every state that the local variable \
`{VARIABLE}` holds while the target's frame is executing — i.e. its value right after it is first bound AND \
its value after every in-place mutation, up to the function's return. (Points where the variable is not yet bound \
contribute nothing.) Take Python's `repr()` of the whole list in each such state (CPython 3.11; the list's repr \
contains the `repr()` of each string element, so e.g. a regex backslash inside an element appears doubled, as \
in `['a\\\\.b']`, and non-printable characters appear as escape sequences while printable non-ASCII characters \
appear literally). Report the set of DISTINCT repr strings (exact duplicates, whether from the same or different \
invocations/methods, are reported once), sorted ascending by plain Python string comparison (`sorted()` on the \
`str` values, i.e. Unicode code-point order).

Answer format: a JSON object `{{"unique_values": [...]}}` whose list contains those repr strings (each a JSON \
string) in the order described. No other keys.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {path}")

    n_events = 0
    n_calls = 0
    values: set[str] = set()
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE_REL):
            continue
        if not m.group("func").endswith("." + TARGET_SUFFIX):
            continue
        n_events += 1
        if m.group("event") == "call":
            n_calls += 1
        idx = raw.rfind(" locals=")
        if idx < 0:
            fail(f"no locals in trace line: {raw[:200]}")
        try:
            loc = ast.literal_eval(raw[idx + len(" locals="):])
        except (ValueError, SyntaxError) as exc:
            fail(f"cannot parse locals ({exc}): {raw[:200]}")
        if VARIABLE in loc:
            val = loc[VARIABLE]
            if len(val) > TRACE_REPR_LIMIT:
                fail(f"repr of {VARIABLE} truncated by tracer; cannot compute exact answer")
            values.add(val)

    if n_events == 0 or n_calls == 0:
        fail("zero events for the target function in the trace")
    if not values:
        fail(f"variable {VARIABLE} never observed")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"invocations={n_calls} events={n_events} unique={len(values)}")
    print(json.dumps(oracle["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
