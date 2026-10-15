#!/usr/bin/env python
"""Parse the from_timestamp trace into per-type exception observation counts."""

import argparse
import builtins
import json
import re
import sys
from collections import Counter

TARGET_FUNC = "marshmallow.utils.from_timestamp"
TARGET_FILE_SUFFIX = "src/marshmallow/utils.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_.]*): ")

QUESTION = (
    "Consider the test class `TestFromTimestampExceptions` in "
    "`marshmallow_qa/utils_from_timestamp_m5_exceptions/files/testcase.py`. Run ALL of its "
    "test methods with pytest (e.g. `pytest marshmallow_qa/utils_from_timestamp_m5_exceptions/"
    "files/testcase.py::TestFromTimestampExceptions`). The answer aggregates over every test "
    "method in that class and over every invocation of the target function "
    "`marshmallow.utils.from_timestamp` (defined in `src/marshmallow/utils.py`). Note that "
    "`from_timestamp_ms` is a different function and is NOT part of the target.\n\n"
    "For each exception type, how many times was an exception of that type OBSERVED in a "
    "`from_timestamp` frame across the whole run?\n\n"
    "Observation rule: an exception is observed in a `from_timestamp` frame each time it is "
    "either (a) raised by code executing directly in that frame (a `raise` statement in "
    "`from_timestamp`, including a new exception raised inside one of its `except` handlers, "
    "or an error raised by a C-implemented builtin/type called directly from that frame, e.g. "
    "`float(...)` or `datetime.fromtimestamp(...)`), or (b) propagated into that frame from a "
    "Python-level callee (for example a user-defined or stdlib `__float__` method invoked "
    "by `float(value)`). This is exactly the moments at which Python's `sys.settrace` would "
    "report an `exception` event for that frame. Each such moment counts once. An exception "
    "that is caught by an `except` handler inside `from_timestamp` still counts once (it was "
    "observed before being handled), and if the handler raises a NEW exception, that new "
    "exception counts as a separate observation. A single exception object that propagates "
    "out of `from_timestamp` is counted only once for that frame (leaving the frame does not "
    "count again). Exceptions that are raised and fully handled inside a callee (never "
    "reaching `from_timestamp`) do NOT count. Exceptions caught by the test code after they "
    "leave `from_timestamp` are not observed again in the target frame.\n\n"
    "Counts are totals over ALL invocations and ALL test methods: the same type observed in "
    "five different invocations contributes five.\n\n"
    "Naming: use bare `type(exc).__name__` for built-in exception types (e.g. `KeyError`, "
    "never `builtins.KeyError`) and `module.QualName` for all other exception types (e.g. "
    "`json.decoder.JSONDecodeError`). Report the concrete type of the exception object, not a "
    "base class and not an alias spelling.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts`, whose value is a "
    "list of objects `{\"count\": <int>, \"exception_type\": <str>}`. Include every type that "
    "was observed at least once (no zero counts). Sort the list by `exception_type` ascending "
    "(plain code-point string order); since each type appears exactly once, no tie-break is "
    "needed."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def type_label(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    if "." in name:
        return name
    fail(f"non-builtin exception type {name!r} lacks a module qualifier in trace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not lines:
        fail("trace log is empty")

    counts = Counter()
    target_events = 0
    calls = 0
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        if not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        target_events += 1
        event = m.group("event")
        if event == "call":
            calls += 1
        elif event == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                fail(f"cannot parse exception event: {line}")
            counts[type_label(em.group("name"))] += 1

    if target_events == 0 or calls == 0:
        fail("no events for the target function in the trace")
    if not counts:
        fail("no exception events observed in the target function")

    answer = {
        "exception_type_counts": [
            {"count": counts[k], "exception_type": k} for k in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_type_counts": [{"count": "int", "exception_type": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))
    print(f"invocations={calls} target_events={target_events}", file=sys.stderr)


if __name__ == "__main__":
    main()
