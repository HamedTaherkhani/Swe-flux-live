#!/usr/bin/env python
"""Trace log -> oracle.json for multiline_adjlist_parse_multiline_adjlist_m5_exceptions."""

import argparse
import builtins
import json
import re
import sys
from collections import Counter

TARGET_QUALNAME = "networkx.readwrite.multiline_adjlist.parse_multiline_adjlist"
TARGET_FILE = "networkx/readwrite/multiline_adjlist.py"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<type>[^:\s]+): ")

QUESTION = (
    "Consider the test class `TestMultilineAdjlistReadScenarios` in "
    "`networkx_qa/multiline_adjlist_parse_multiline_adjlist_m5_exceptions/files/testcase.py`. "
    "Run ALL 14 of its test methods (e.g. with "
    "`pytest networkx_qa/multiline_adjlist_parse_multiline_adjlist_m5_exceptions/files/testcase.py::TestMultilineAdjlistReadScenarios`). "
    "None of them calls the target directly; every method reaches it through `networkx.read_multiline_adjlist` "
    "(or `write_multiline_adjlist` followed by `read_multiline_adjlist`). "
    "The target function is `networkx.readwrite.multiline_adjlist.parse_multiline_adjlist`, defined in "
    "`networkx/readwrite/multiline_adjlist.py`.\n\n"
    "Question: across the whole run (all invocations of the target in all 14 test methods together), how many "
    "times was an exception of each type observed in the target function's own frame?\n\n"
    "Observation rule: an exception is observed in the target frame each time it becomes the active exception in "
    "that frame -- either because a statement executing in that frame raises it (an explicit `raise`, or a built-in "
    "operation/C-level call such as `int(...)`, `next(...)`, tuple unpacking or `**` unpacking raising it) or "
    "because it propagates into the frame from a Python callee (e.g. from `ast.literal_eval`). Every such observation "
    "counts once, whether the exception is later caught and swallowed in the target frame, converted into another "
    "exception, or escapes the frame. A `raise NewError(...) from err` inside an `except` block is a separate "
    "observation of the NEW exception (the original `err` was already counted when it was first observed). "
    "Exceptions raised and fully handled inside a callee that never reach the target frame do not count. The normal "
    "termination of a `for` loop over its iterable is not an exception observation. No exception in this run is "
    "re-raised by a bare `raise` in the target frame, so no single exception object is counted twice. Counts are "
    "totals over ALL invocations and ALL test methods (the same type observed in five methods contributes five).\n\n"
    "Exception type naming: use bare `type(exc).__name__` for built-in exception classes (e.g. `KeyError`, never "
    "`builtins.KeyError`) and `module.QualName` for any other class (e.g. "
    "`networkx.exception.NetworkXError`). Use the concrete class of the exception object, not a base class.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts`, whose value is a list of objects "
    "`{\"count\": <int>, \"exception_type\": <str>}`, one entry per distinct exception type observed at least once "
    "(types never observed are omitted; no entry has count 0). Sort the list by `exception_type` ascending "
    "(plain code-point string order); since each type appears once, no further tie-break is needed."
)


def builtin_name(name):
    obj = getattr(builtins, name, None)
    return isinstance(obj, type) and issubclass(obj, BaseException)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except OSError as e:
        sys.exit(f"ERROR: cannot read trace log {args.trace_log}: {e}")
    if not raw:
        sys.exit("ERROR: trace log is empty")

    counts = Counter()
    n_target = n_calls = n_lines = 0
    for line in raw:
        m = EVENT_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_FILE):
            continue
        n_target += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "line":
            n_lines += 1
        elif ev == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                sys.exit(f"ERROR: cannot parse exception event: {line}")
            name = em.group("type")
            if not builtin_name(name):
                sys.exit(f"ERROR: non-builtin exception {name!r}; module unknown from trace")
            counts[name] += 1

    if n_target == 0 or n_calls == 0:
        sys.exit("ERROR: no events for the target function in the trace")
    if not counts:
        sys.exit("ERROR: no exception events observed for the target")

    answer = {
        "exception_type_counts": [
            {"count": counts[t], "exception_type": t} for t in sorted(counts)
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
    print(f"target calls={n_calls} line events={n_lines}")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
