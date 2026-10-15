#!/usr/bin/env python
"""Parse the List._deserialize trace into per-type exception observation counts."""

import argparse
import builtins
import importlib
import json
import re
import sys
from collections import Counter

TARGET_QUALNAME = "marshmallow.fields.List._deserialize"
TARGET_FILE = "src/marshmallow/fields.py"

# Modules searched to qualify non-builtin exception class names.
CANDIDATE_MODULES = ["marshmallow.exceptions", "decimal", "json", "uuid", "datetime"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    "Consider the test class `ListLoadScenarios` in "
    "`marshmallow_qa/fields_deserialize_m5_exceptions_2/files/testcase.py`. Run ALL of its "
    "test methods (the whole class, e.g. `pytest "
    "marshmallow_qa/fields_deserialize_m5_exceptions_2/files/testcase.py::ListLoadScenarios`). "
    "Across the entire run, aggregated over every test method and every invocation, count how "
    "many times each exception type is observed in a frame of the target function "
    "`marshmallow.fields.List._deserialize` (the `_deserialize` method of class `List` defined "
    "in `src/marshmallow/fields.py`). "
    "Observation rule: one observation = one 'exception' event that Python's `sys.settrace` "
    "line-level tracing delivers for a frame executing `List._deserialize`. This happens when an "
    "exception is raised by a `raise` statement in that frame, or when an exception propagates "
    "into that frame from a callee (including from code invoked implicitly by a `for` loop's "
    "iteration protocol; e.g. a `StopIteration` raised by a Python-level `__next__` that ends "
    "the loop is delivered to the looping frame and DOES count). Exceptions raised and fully "
    "handled inside a callee, never reaching the target frame, do NOT count. Each such event "
    "counts once, whether the exception is then caught by the target's `except` clause or "
    "escapes the frame; an exception that leaves the frame is not counted again for that frame. "
    "Every distinct frame counts separately: when `List._deserialize` is (indirectly) nested "
    "inside another `List._deserialize` call, one exception passing through both frames counts "
    "once per frame. A new `raise` statement in the frame (even if it creates a new exception "
    "of the same type) is a separate observation. "
    "Counts are totals over all invocations (an invocation = one call of the function) and all "
    "test methods, so the same type observed in five invocations contributes five. "
    "Exception type naming: use bare `type(exc).__name__` for built-in exceptions (e.g. "
    "`ValueError`, never `builtins.ValueError`), and `module.QualName` using the class's "
    "defining module `__module__` for all others (e.g. `json.decoder.JSONDecodeError`). "
    "Answer format: a JSON object with key `exception_type_counts` whose value is a list of "
    "objects `{\"exception_type\": <str>, \"count\": <int>}`, one per exception type observed at "
    "least once (types never observed are omitted; no zero counts), sorted by `exception_type` "
    "ascending using plain case-sensitive string (code point) comparison; since each type "
    "appears exactly once, no further tie-break is needed."
)

TEMPLATE = {"exception_type_counts": [{"count": "int", "exception_type": "str"}]}


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    hits = set()
    for modname in CANDIDATE_MODULES:
        mod = importlib.import_module(modname)
        cls = getattr(mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            hits.add("%s.%s" % (cls.__module__, cls.__qualname__))
    if len(hits) != 1:
        sys.exit("ERROR: cannot uniquely qualify exception type %r: %r" % (name, sorted(hits)))
    return hits.pop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sys.path.insert(0, "src")
    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit("ERROR: trace log not found: %s" % args.trace_log)
    if not lines:
        sys.exit("ERROR: trace log is empty")

    counts = Counter()
    target_events = 0
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_FILE):
            continue
        target_events += 1
        if m.group("event") != "exception":
            continue
        em = EXC_RE.match(m.group("rest"))
        if not em:
            sys.exit("ERROR: unparsable exception event: %s" % line)
        counts[qualify(em.group("name"))] += 1

    if target_events == 0:
        sys.exit("ERROR: zero events for %s in trace" % TARGET_QUALNAME)
    if not counts:
        sys.exit("ERROR: no exception events observed for target")

    answer = {
        "exception_type_counts": [
            {"count": counts[k], "exception_type": k} for k in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))
    print("target events: %d" % target_events)


if __name__ == "__main__":
    main()
