#!/usr/bin/env python
"""Build oracle.json: distinct repr values of `original` in Nested.schema."""

import argparse
import ast
import json
import re
import sys

TARGET = "marshmallow.fields.Nested.schema"
TARGET_PATH = "src/marshmallow/fields.py"
VARIABLE = "original"
REPR_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=.*?)?(?: retval=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the test class `TestNestedSchemaState` in "
    "`marshmallow_qa/fields_schema_m3_state/files/testcase.py`. Run ALL of its test methods "
    "(pytest ids `marshmallow_qa/fields_schema_m3_state/files/testcase.py::TestNestedSchemaState::test_*`, "
    "12 methods); the answer aggregates over every one of them and over every invocation of the "
    "property getter `marshmallow.fields.Nested.schema` (the `@property def schema` of class "
    "`Nested` in `src/marshmallow/fields.py`) that happens while those tests run. An invocation is "
    "one call of that getter function (including calls on the cached path that simply return "
    "`self._schema`, and calls that end by propagating an exception). "
    "Observe the local variable `original` of that getter: every time an assignment statement "
    "`original = ...` inside the getter completes, record `repr(original)` as it is right after "
    "that assignment (the builtin `repr` of the bound object at that moment). Invocations that "
    "never assign `original` contribute nothing. Reprs use Python spellings exactly as `repr()` "
    "produces them, e.g. a dict keys view looks like `dict_keys(['p', 'q'])`, marshmallow's "
    "`OrderedSet` looks like `OrderedSet(['p', 'q'])` (or `OrderedSet()` when empty), builtin sets "
    "and frozensets use their builtin repr, a tuple is `('p',)`, a list is `['p']`, with single-quoted strings. "
    "Answer with JSON `{\"unique_values\": [...]}` whose list contains every DISTINCT recorded "
    "repr string (duplicates removed by exact string equality), sorted ascending by plain Python "
    "string ordering (`sorted()` on the strings, i.e. Unicode code point order, so uppercase "
    "letters sort before lowercase, e.g. `\"Zz\"` before `\"aa\"`). Each element is the repr text "
    "itself as a JSON string."
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
    n_calls = 0
    n_events = 0
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET or not m.group("file").endswith(TARGET_PATH):
            continue
        n_events += 1
        if m.group("event") == "call":
            n_calls += 1
        try:
            loc = ast.literal_eval(m.group("locals"))
        except (ValueError, SyntaxError) as exc:
            fail(f"cannot parse locals: {exc}: {line[:200]}")
        if VARIABLE in loc:
            val = loc[VARIABLE]
            if len(val) > REPR_LIMIT:
                fail(f"repr of {VARIABLE} was truncated: {val[:80]}")
            values.add(val)

    if n_events == 0 or n_calls == 0:
        fail(f"no trace events for {TARGET}")
    if not values:
        fail(f"variable {VARIABLE} never observed")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"calls={n_calls} events={n_events} distinct={len(values)}")


if __name__ == "__main__":
    main()
