#!/usr/bin/env python
"""Trace -> oracle.json for fields_deserialize_m5_exceptions (M5_Exceptions)."""

import argparse
import builtins
import json
import re
import sys
from collections import Counter

TARGET_SUFFIX = "marshmallow.fields.Enum._deserialize"
TARGET_FILE = "src/marshmallow/fields.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    "Consider the test class `TestEnumDeserializeExceptions` in "
    "`marshmallow_qa/fields_deserialize_m5_exceptions/files/testcase.py`, run with "
    "`pytest marshmallow_qa/fields_deserialize_m5_exceptions/files/testcase.py::TestEnumDeserializeExceptions` "
    "(all of its test methods, aggregated together). Focus on the method "
    "`marshmallow.fields.Enum._deserialize` defined in `src/marshmallow/fields.py` "
    "(the `_deserialize` method of class `Enum`; NOT any other field class's `_deserialize`). "
    "Across ALL invocations of that method during ALL test methods of the class, count how many "
    "times each exception type is observed in the `Enum._deserialize` frame.\n\n"
    "Observation rule: an exception is observed in the frame when it is raised by code executing "
    "in that exact frame (e.g. a `raise` statement in the method body), OR when it propagates "
    "into that frame out of a callee (e.g. an exception escaping a call made on one of the method's "
    "lines). Each such event counts once per frame invocation per exception: an exception that "
    "propagates into the frame and is then caught by an `except` clause in the frame counts once; "
    "an exception that propagates in and is not caught (so it continues to propagate out of the "
    "method) also counts exactly once (leaving the frame does not count again). A new exception "
    "raised inside an `except` handler is a separate observation of its own type (in addition to "
    "the one that was caught). Exceptions raised AND fully handled inside a callee (never escaping "
    "the callee into the `Enum._deserialize` frame) do NOT count. Exceptions in other frames "
    "(callers such as `List._deserialize`, `Schema` methods, or the test itself) do NOT count. "
    "Counts are totals over all invocations and all test methods: the same type observed in five "
    "different invocations contributes five.\n\n"
    "Naming: use bare `type(exc).__name__` for built-in exception classes (e.g. `ZeroDivisionError`, "
    "never `builtins.ZeroDivisionError`), and `module.QualName` (i.e. "
    "`f\"{type(exc).__module__}.{type(exc).__qualname__}\"`, e.g. `json.decoder.JSONDecodeError`) "
    "for every non-built-in exception class.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts`, whose value is a list "
    "of objects `{\"count\": <int>, \"exception_type\": <str>}`, one per exception type observed at "
    "least once (types never observed are omitted; no entry has count 0). Sort the list by "
    "`exception_type` ascending (plain Python string ordering, case-sensitive); since each type "
    "appears exactly once, there are no ties."
)


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    import marshmallow.exceptions as mexc

    obj = getattr(mexc, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return f"{obj.__module__}.{obj.__qualname__}"
    sys.exit(f"ERROR: cannot resolve module for exception type {name!r}")


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
    n_events = 0
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        n_events += 1
        if m.group("event") != "exception":
            continue
        em = EXC_RE.match(m.group("rest"))
        if not em:
            sys.exit(f"ERROR: unparseable exception event: {raw}")
        counts[qualify(em.group("name"))] += 1

    if n_events == 0:
        sys.exit("ERROR: zero trace events for Enum._deserialize")
    if not counts:
        sys.exit("ERROR: no exception events observed for Enum._deserialize")

    answer = {
        "exception_type_counts": [
            {"count": counts[k], "exception_type": k} for k in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
