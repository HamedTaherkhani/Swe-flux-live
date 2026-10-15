#!/usr/bin/env python
"""Parse the UUID._validated trace into per-type exception observation counts."""

import argparse
import builtins
import json
import re
import sys
from collections import Counter

TARGET_QUALNAME = "marshmallow.fields.UUID._validated"
TARGET_FILE = "src/marshmallow/fields.py"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*):")

NON_BUILTIN_MODULES = {"ValidationError": "marshmallow.exceptions"}

QUESTION = (
    "Run the pytest test class `TestUUIDValidated` in "
    "`marshmallow_qa/fields_validated_m5_exceptions_2/files/testcase.py` (all 12 test "
    "methods; the answer aggregates over ALL of them). Consider every invocation of the "
    "method `marshmallow.fields.UUID._validated` defined in `src/marshmallow/fields.py` "
    "(an invocation = one call of that function's frame during the run). "
    "An exception is OBSERVED in the target frame each time an exception is raised by a "
    "statement executing in that frame, OR propagates into that frame out of a callee "
    "(e.g. raised inside `uuid.UUID.__init__` or inside a `replace` method and not caught "
    "there). Exceptions that are raised and fully caught inside a callee (never reaching the "
    "target frame) are NOT observed. Each exception object is counted once per frame "
    "in which it is observed: a propagated-in exception counts once when it arrives, an "
    "exception raised by a `raise` statement in the frame counts once at that statement, "
    "and evaluating an `except` clause or letting the exception continue to propagate out "
    "of the frame does not add another observation (no re-raise of the same object occurs "
    "within the frame). An exception raised with `raise X from Y` is a new observation of X, "
    "independent of the earlier observation of Y. "
    "For each exception type observed at least once, report the TOTAL number of "
    "observations summed over all invocations and all test methods (the same type observed "
    "in five invocations contributes 5). Types never observed are omitted. "
    "Exception type naming: bare `type(exc).__name__` for built-in exceptions (e.g. "
    "`IndexError`, never `builtins.IndexError`); for all other exceptions use "
    "`type(exc).__module__ + '.' + type(exc).__qualname__` (e.g. `json.decoder.JSONDecodeError`). "
    "Answer as JSON `{\"exception_type_counts\": [{\"count\": <int>, \"exception_type\": <str>}, ...]}` "
    "where `count` is a JSON integer, sorted by `exception_type` ascending (plain codepoint "
    "string comparison; types are unique so no tie-break is needed)."
)


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    if name in NON_BUILTIN_MODULES:
        return f"{NON_BUILTIN_MODULES[name]}.{name}"
    sys.exit(f"ERROR: cannot qualify non-builtin exception type {name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log missing: {args.trace_log}")
    if not lines:
        sys.exit("ERROR: trace log is empty")

    counts = Counter()
    n_events = n_calls = 0
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_FILE):
            continue
        n_events += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "exception":
            em = EXC_RE.search(m.group("rest"))
            if not em:
                sys.exit(f"ERROR: unparsable exception event: {raw}")
            counts[qualify(em.group("name"))] += 1

    if n_events == 0 or n_calls == 0:
        sys.exit("ERROR: zero events for target function in trace")
    if not counts:
        sys.exit("ERROR: no exception events observed for target function")

    answer = {
        "exception_type_counts": [
            {"count": counts[t], "exception_type": t} for t in sorted(counts)
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
    print(f"target calls: {n_calls}, target events: {n_events}")


if __name__ == "__main__":
    main()
