#!/usr/bin/env python
"""Trace -> oracle.json for matcher_match_m5_exceptions (M5_Exceptions)."""
import argparse
import builtins
import importlib
import json
import re
import sys
from collections import Counter

TARGET_QUALNAME = "werkzeug.routing.matcher.StateMachineMatcher.match"
CANDIDATE_MODULES = [
    "werkzeug.routing.matcher",
    "werkzeug.routing.exceptions",
    "werkzeug.routing.converters",
    "werkzeug.routing.map",
    "werkzeug.exceptions",
]

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$")
EXC_RE = re.compile(r" exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    "Run the whole test class `MatcherExceptionScenarios` in "
    "`werkzeug_qa/matcher_match_m5_exceptions/files/testcase.py` (all 13 of its test methods, e.g. "
    "pytest id `werkzeug_qa/matcher_match_m5_exceptions/files/testcase.py::MatcherExceptionScenarios::test_static_hits_only`). "
    "Consider every invocation of the method `StateMachineMatcher.match` defined in "
    "`src/werkzeug/routing/matcher.py` (qualname `werkzeug.routing.matcher.StateMachineMatcher.match`; it is "
    "reached indirectly through `MapAdapter.match`). An exception is 'observed in the target frame' each time it "
    "is raised by a statement executing in the frame of `StateMachineMatcher.match` itself, or propagates into that "
    "frame out of a callee (including out of its nested helper `_match` and out of converter `to_python` calls). "
    "Each such observation counts once per frame per exception object: an exception raised inside the nested "
    "`_match` function and passing up through several recursive `_match` frames is counted only once, when it "
    "arrives in the `StateMachineMatcher.match` frame; an exception that propagates in and is then caught by an "
    "`except` clause in that frame still counts once; and a new exception raised from inside that `except` "
    "clause (e.g. `raise X(...) from None` / `from e`) counts as a separate observation. Exceptions that are raised "
    "and fully handled inside a callee (never reaching the `StateMachineMatcher.match` frame) do not count, and "
    "neither do exceptions raised by callers after `StateMachineMatcher.match` has returned or raised. "
    "Counts are totals over ALL invocations of the target in ALL 13 test methods (the same type observed in "
    "five different invocations contributes five). "
    "Answer with JSON `{\"exception_type_counts\": [{\"count\": int, \"exception_type\": str}, ...]}` containing one "
    "entry per exception type observed at least once (types never observed are omitted; no zero counts). "
    "Name each type as bare `type(exc).__name__` for built-in exceptions (e.g. `KeyError`, never "
    "`builtins.KeyError`) and as `type(exc).__module__ + '.' + type(exc).__qualname__` for all other exceptions, "
    "using the module where the class is defined (e.g. `werkzeug.exceptions.BadRequest`). Classify by the exact "
    "runtime class, not by any base class. Sort entries by `exception_type` ascending (plain Python string "
    "ordering, case-sensitive); types are unique so no further tie-break is needed."
)


def resolve_type_name(name):
    if isinstance(getattr(builtins, name, None), type) and issubclass(getattr(builtins, name), BaseException):
        return name
    found = set()
    for modname in CANDIDATE_MODULES:
        mod = importlib.import_module(modname)
        obj = getattr(mod, name, None)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            found.add(f"{obj.__module__}.{obj.__qualname__}")
    if len(found) != 1:
        sys.exit(f"ERROR: cannot uniquely resolve exception type {name!r}: {sorted(found)}")
    return found.pop()


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

    target_events = 0
    calls = 0
    counts = Counter()
    for line in lines:
        m = LINE_RE.match(line)
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        target_events += 1
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                sys.exit(f"ERROR: unparsable exception event: {line}")
            counts[resolve_type_name(em.group("name"))] += 1

    if target_events == 0 or calls == 0:
        sys.exit("ERROR: no events for target function in trace")
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
        "template_answer": {"exception_type_counts": [{"count": "int", "exception_type": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"target invocations: {calls}, target events: {target_events}")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
