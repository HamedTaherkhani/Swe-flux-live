#!/usr/bin/env python
"""Trace -> oracle.json for fields_validated_m5_exceptions (M5_Exceptions)."""

import argparse
import builtins
import decimal
import importlib
import json
import re
import sys
from collections import Counter

TARGET_SUFFIX = "marshmallow.fields.Number._validated"
TARGET_FILE = "src/marshmallow/fields.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

TEST_PATH = "marshmallow_qa/fields_validated_m5_exceptions/files/testcase.py"

QUESTION = (
    f"Consider the test class `TestNumberValidatedExceptions` in `{TEST_PATH}`, run with "
    f"`pytest {TEST_PATH}::TestNumberValidatedExceptions` (all of its test methods, "
    "aggregated together). Focus on the method `marshmallow.fields.Number._validated` defined in "
    "`src/marshmallow/fields.py` (the `_validated` method of the abstract class `Number`, which the "
    "test calls directly as `Number._validated(field, value)`; NOT the overrides `Integer._validated`, "
    "`Float._validated`, `Decimal._validated` or `UUID._validated`, none of which run here). Across ALL "
    "invocations of `Number._validated` during ALL test methods of the class, count how many times "
    "each exception type is observed in the `Number._validated` frame.\n\n"
    "Observation rule: an exception is observed in the frame when it is raised by code executing in "
    "that exact frame (a `raise` statement in the method body), OR when it propagates into that frame "
    "out of a callee (e.g. escaping `self._format_num(value)` / the field's `num_type`, or escaping "
    "`self.make_error(...)`). Each such event counts once per frame invocation per exception: an "
    "exception that propagates in and is caught by an `except` clause of the method counts once; an "
    "exception that propagates in and is NOT caught by the method (so it continues out of the method) "
    "also counts exactly once (leaving the frame does not count again). A new exception raised while "
    "handling another one inside an `except` clause (including one that escapes from a `make_error` call "
    "evaluated inside the handler) is a separate observation of its own type, in addition to the one "
    "that was caught. There is no bare re-raise of the same exception object in this method; each "
    "observation is a distinct exception. Exceptions raised AND fully handled inside a callee (never "
    "escaping into the `Number._validated` frame) do NOT count. Exceptions in other frames (the test's "
    "helper `_run`, the `num_type` callables, `make_error`, etc.) do NOT count on their own. Counts are "
    "totals over all invocations and all test methods: the same type observed in five different "
    "invocations contributes five.\n\n"
    "Naming: use bare `type(exc).__name__` for built-in exception classes (e.g. `IndexError`, "
    "never `builtins.IndexError`), and `module.QualName` (i.e. "
    "`f\"{type(exc).__module__}.{type(exc).__qualname__}\"`, e.g. `json.decoder.JSONDecodeError`) for "
    "every non-built-in exception class. Use the concrete runtime class of the exception object, not "
    "the class named in an `except` clause.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts`, whose value is a list of "
    "objects `{\"count\": <int>, \"exception_type\": <str>}`, one per exception type observed at least "
    "once (types never observed are omitted; no entry has count 0). Sort the list by `exception_type` "
    "ascending (plain Python string ordering, case-sensitive, so uppercase letters sort before "
    "lowercase); since each type appears exactly once, there are no ties."
)

CANDIDATE_MODULES = ["marshmallow.exceptions", "decimal", "fractions"]


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    for modname in CANDIDATE_MODULES:
        mod = importlib.import_module(modname)
        obj = getattr(mod, name, None)
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
        sys.exit("ERROR: zero trace events for Number._validated")
    if not counts:
        sys.exit("ERROR: no exception events observed for Number._validated")

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
