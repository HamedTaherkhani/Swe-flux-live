#!/usr/bin/env python
"""Derive the M3_ProgramState oracle for werkzeug.security._hash_internal."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FUNC = "werkzeug.security._hash_internal"
TARGET_FILE = "src/werkzeug/security.py"
TEST_FILE = "werkzeug_qa/security_hash_internal_m3_state/files/testcase.py"
TEST_CLASS = "TestPasswordHashState"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=(?P<retval>.*?)| exc=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = f"""\
Run the whole pytest class `{TEST_FILE}::{TEST_CLASS}` (ALL of its test \
methods; the answer aggregates over every one of them, regardless of the order \
in which they execute). Consider every invocation of the module-level function \
`werkzeug.security._hash_internal` defined in `{TARGET_FILE}` (an invocation is \
one call of that function, whether reached via `generate_password_hash` or \
`check_password_hash`). Only invocations that RETURN NORMALLY (return a tuple) \
are counted; invocations that raise or propagate any exception contribute nothing.

For each counted invocation, look at the function's local variables at the \
moment it returns (note `method` is the local re-bound on the first line of the \
function, i.e. the part before the first ':'), and build one entry:
- if local `method` == 'scrypt': the Python `repr()` of the 2-tuple \
`(method, maxmem)`;
- if local `method` == 'pbkdf2': the Python `repr()` of the 3-tuple \
`(method, hash_name, iterations)`.
All values are the actual Python objects held by those locals (str or int), so \
e.g. a hypothetical entry looks like `('scrypt', 123)` or `('pbkdf2', 'sha3_256', 7)` \
(single-quoted strings, ints without separators or quotes, ", " between items).

Answer with JSON `{{"unique_values": [...]}}`: the list of DISTINCT entry \
strings (duplicates removed), sorted ascending by plain Python string \
comparison of the repr strings (Unicode code-point / lexicographic order, NOT \
numeric order)."""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_source():
    src = Path(TARGET_FILE)
    if not src.exists():
        fail(f"target source missing: {TARGET_FILE}")
    tree = ast.parse(src.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_hash_internal":
            return
    fail("_hash_internal not found in source")


def parse_events(path):
    p = Path(path)
    if not p.exists():
        fail(f"trace log missing: {path}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log empty: {path}")
    events = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        events.append(
            (
                int(m.group("line")),
                m.group("event"),
                m.group("retval"),
                ast.literal_eval(m.group("locals")),
            )
        )
    if not events:
        fail("zero events for target function in trace")
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    check_source()
    events = parse_events(args.trace_log)

    calls = sum(1 for e in events if e[1] == "call")
    returns = [e for e in events if e[1] == "return"]
    if calls == 0 or calls != len(returns):
        fail(f"inconsistent call/return counts: {calls} vs {len(returns)}")

    values = set()
    for _line, _ev, retval, loc in returns:
        if retval is None or retval == "None":
            continue  # exited via exception
        if not retval.startswith("("):
            fail(f"unexpected retval: {retval!r}")
        method = ast.literal_eval(loc["method"])
        if method == "scrypt":
            entry = (method, ast.literal_eval(loc["maxmem"]))
        elif method == "pbkdf2":
            entry = (
                method,
                ast.literal_eval(loc["hash_name"]),
                ast.literal_eval(loc["iterations"]),
            )
        else:
            fail(f"normal return with unexpected method {method!r}")
        values.add(repr(entry))

    if not values:
        fail("no normally-returning invocations found")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
