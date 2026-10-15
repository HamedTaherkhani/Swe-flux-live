#!/usr/bin/env python
"""Build oracle.json: distinct repr values of `data` in Schema._invoke_processors."""

import argparse
import ast
import json
import re
import sys

TARGET = "marshmallow.schema.Schema._invoke_processors"
TARGET_PATH = "src/marshmallow/schema.py"
REPR_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=.*?)?(?: retval=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the test class `TestInvokeProcessorsState` in "
    "`marshmallow_qa/schema_invoke_processors_m3_state/files/testcase.py`. Run ALL of its "
    "test methods (pytest ids "
    "`marshmallow_qa/schema_invoke_processors_m3_state/files/testcase.py::TestInvokeProcessorsState::test_*`, "
    "12 methods); the answer aggregates over every one of them, and every invocation of the "
    "method `marshmallow.schema.Schema._invoke_processors` (defined in `src/marshmallow/schema.py`) "
    "that happens during those tests (an invocation = one call of that function, whatever schema "
    "subclass it is called on and whichever caller reaches it). "
    "Within each invocation, observe the local variable `data` (the keyword parameter that the "
    "function rebinds inside its loop) at these points: (a) its value on entry to the function, "
    "i.e. the argument it received; and (b) its value immediately after EACH completed assignment "
    "statement `data = ...` inside the function body (both the list-comprehension assignments and "
    "the direct `processor(...)` assignments). An assignment whose right-hand side raises never "
    "completes and contributes nothing. Values are taken at the moment of observation, so if an "
    "object is later mutated in place, the earlier observation keeps the earlier state. "
    "For each observation, take Python `repr(data)` (builtin repr: dicts in insertion order with "
    "single-quoted string keys, e.g. `{'k': 1}`; lists as `[...]`; tuples as `(...)`; strings as "
    "`'abc'`; Python spellings `None`/`True`/`False`). "
    "Answer with JSON `{\"unique_values\": [...]}` where the list contains every DISTINCT repr string "
    "observed (duplicates removed, exact string equality), sorted ascending by plain Python string "
    "ordering (`sorted()` on the str values, i.e. Unicode code point order, so e.g. `\"['x']\"` sorts "
    "before `\"{'x': 1}\"`). Each list element is the repr text itself as a JSON string."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        fail(f"cannot read trace log: {exc}")
    if not raw:
        fail("trace log is empty")

    values = set()
    depth = 0
    n_calls = 0
    n_events = 0
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET or not m.group("file").endswith(TARGET_PATH):
            continue
        n_events += 1
        event = m.group("event")
        try:
            loc = ast.literal_eval(m.group("locals"))
        except (ValueError, SyntaxError) as exc:
            fail(f"cannot parse locals: {exc}: {line[:200]}")
        if event == "call":
            if depth != 0:
                fail("nested invocation of target; observation model would be ambiguous")
            depth = 1
            n_calls += 1
            if "data" not in loc:
                fail("call event without `data`")
        if depth != 1:
            fail(f"event outside an invocation: {line[:200]}")
        if "data" in loc:
            val = loc["data"]
            if len(val) > REPR_LIMIT and val.endswith("..."):
                fail(f"truncated repr encountered: {val[:80]}")
            values.add(val)
        if event == "return":
            depth = 0

    if n_calls == 0 or n_events == 0:
        fail("no events for target function in trace")
    if not values:
        fail("no `data` values observed")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={n_calls} events={n_events} unique_values={len(values)}")


if __name__ == "__main__":
    main()
