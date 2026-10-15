#!/usr/bin/env python
"""Trace -> oracle.json for wsgi_readinto_m5_exceptions (M5_Exceptions, template 1).

Answer: per-type counts of exception events observed in the frame of
``werkzeug.wsgi._LimitedStream.readinto`` over all test methods.
"""
from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from collections import Counter

TARGET_FUNC = "werkzeug.wsgi._LimitedStream.readinto"
TARGET_FILE_SUFFIX = "src/werkzeug/wsgi.py"

# Modules searched to map a traced class __name__ to its defining module.
CANDIDATE_MODULES = ["io", "werkzeug.exceptions"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>[A-Za-z_][A-Za-z0-9_]*):)?"
)

TEST_PATH = "werkzeug_qa/wsgi_readinto_m5_exceptions/files/testcase.py"
TEST_CLASS = "LimitedStreamReadintoTest"

QUESTION = (
    f"Consider the test file `{TEST_PATH}` and its `unittest.TestCase` class `{TEST_CLASS}`. "
    f"Run ALL test methods of that class with pytest (pytest ids of the form "
    f"`{TEST_PATH}::{TEST_CLASS}::test_<name>`); the answer aggregates over every test method "
    "in the class together. The test methods call the method `werkzeug.wsgi._LimitedStream.readinto` "
    "(defined in `src/werkzeug/wsgi.py`; `LimitedStream` is the public alias of `_LimitedStream`) many "
    "times, directly. An invocation is one call of that method; every invocation in every test method "
    "counts. "
    "Question: for each exception type, how many times was an exception of that type OBSERVED in the "
    "frame of `_LimitedStream.readinto`? Observation rule: an exception is observed once each time it "
    "is raised by code executing in that exact frame, OR propagates into that frame from a callee "
    "(e.g. from the wrapped stream's `readinto`/`read`, or from `self.on_exhausted()` / "
    "`self.on_disconnect()`), whether or not an `except` clause of `readinto` then catches it, and "
    "whether or not it then leaves `readinto`. Each distinct exception object counts exactly once per "
    "invocation in whose frame it is observed (an exception that propagates into the frame and then "
    "straight out of it counts once, not twice; `readinto` contains no `raise` statements, so there are "
    "no re-raises to consider). If, while handling one exception, the frame observes a "
    "second, different exception object (e.g. one raised by a method called from inside an `except` "
    "handler), both are counted, each under its own type. Exceptions raised AND fully handled inside a "
    "callee (never reaching the `readinto` frame) do not count, and exceptions observed only in caller "
    "frames (e.g. the test's own `try`/`except`) do not count. Report the concrete runtime type "
    "`type(exc)` of the exception object, never the class named in an `except` clause. "
    "Naming convention: for built-in exceptions use the bare `type(exc).__name__` (e.g. `KeyError`, "
    "never `builtins.KeyError`); for all other exceptions use `type(exc).__module__ + '.' + "
    "type(exc).__qualname__` (e.g. `json.decoder.JSONDecodeError`), i.e. the module where the class is "
    "defined, not a re-exporting package. Counts are totals over ALL invocations and ALL test methods "
    "(the same type observed in five different invocations contributes five). Every type observed at "
    "least once appears exactly once in the list; types never observed are omitted. Sort the list by "
    "`exception_type` ascending in Python default string order (types are unique, so no tie-break is "
    "needed). Answer as JSON: "
    '{"exception_type_counts": [{"count": <int>, "exception_type": <str>}, ...]}.'
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_name(name: str) -> str:
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    matches = set()
    for mod_name in CANDIDATE_MODULES:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            matches.add(f"{cls.__module__}.{cls.__qualname__}")
    if len(matches) != 1:
        fail(f"cannot resolve exception type name {name!r}: {sorted(matches)}")
    return matches.pop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log missing: {args.trace_log}")
    if not lines:
        fail("trace log is empty")

    n_events = 0
    n_calls = 0
    counts: Counter[str] = Counter()
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC or not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        n_events += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "exception":
            if not m.group("exc"):
                fail(f"unparseable exception event: {raw}")
            counts[resolve_name(m.group("exc"))] += 1

    if n_events == 0 or n_calls == 0:
        fail(f"no events for {TARGET_FUNC} in trace")
    if not counts:
        fail("no exception events observed in target frame")

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
    print(f"target calls={n_calls} events={n_events}")


if __name__ == "__main__":
    main()
