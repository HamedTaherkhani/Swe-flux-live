#!/usr/bin/env python
"""Derive the set of exception types caught inside networkx.convert.to_networkx_graph."""

import argparse
import builtins
import json
import re
import sys

TARGET_QUALNAME = "networkx.convert.to_networkx_graph"
TARGET_FILE_SUFFIX = "/networkx/convert.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>[A-Za-z_][A-Za-z0-9_]*):)?"
)

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/convert_to_networkx_graph_s5_exceptions/files/testcase.py::"
    "TestToNetworkxGraphExceptions::test_mixed_inputs` (test class "
    "`TestToNetworkxGraphExceptions`, its only test method `test_mixed_inputs`). "
    "During this test, the function `networkx.convert.to_networkx_graph` "
    "(defined in `networkx/convert.py`) is invoked many times directly by the "
    "test. Aggregating over ALL of its invocations in this test run, which "
    "exception types are CAUGHT inside `to_networkx_graph`? An exception counts "
    "as caught when it is raised in, or propagates into, the frame of "
    "`to_networkx_graph` (including exceptions raised in callees such as "
    "`from_dict_of_dicts`, `from_dict_of_lists`, `from_edgelist`, "
    "`from_numpy_array`, `empty_graph`, graph methods, or user-supplied "
    "generators that the function consumes) and is matched by one of "
    "`to_networkx_graph`'s own `except` clauses (including the bare `except:`), "
    "regardless of whether that handler then swallows it, falls through, or "
    "raises a different exception. A NEW exception raised by a `raise` "
    "statement inside a handler counts only if some `except` clause of "
    "`to_networkx_graph` in turn catches it; exceptions that leave "
    "`to_networkx_graph` uncaught (propagate to the test) do not count by "
    "themselves. The type reported is the concrete class of the exception "
    "object at the moment it is caught (`type(exc)`), not the class named in "
    "the `except` clause. Naming convention: for built-in exceptions use the "
    "bare `type(exc).__name__` (e.g. `KeyError`, never `builtins.KeyError`); "
    "for all other exceptions use `type(exc).__module__ + '.' + "
    "type(exc).__qualname__` (e.g. `networkx.exception.NodeNotFound`). "
    "Answer as JSON `{\"caught_exception_kinds\": [...]}` where the list "
    "contains each distinct type name exactly once (deduplicated), sorted in "
    "ascending order by plain Python string comparison (code-point order, so "
    "uppercase-initial names sort before lowercase-initial ones)."
)


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    import networkx.exception as nxe

    obj = getattr(nxe, name, None)
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
            raw = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log not found: {args.trace_log}")
    if not raw:
        sys.exit("ERROR: trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        events.append((m.group("event"), int(m.group("lineno")), m.group("exc")))

    if not events:
        sys.exit("ERROR: no events for target function in trace")
    if not any(e[0] == "call" for e in events):
        sys.exit("ERROR: no call events for target function")

    # The target is never re-entered recursively, so events of one invocation
    # are contiguous. An exception event followed by a line event of the same
    # invocation means a handler in the frame took it; followed by a return
    # event means it propagated out.
    caught = set()
    n_exc = 0
    for i, (ev, _lineno, exc) in enumerate(events):
        if ev != "exception":
            continue
        n_exc += 1
        if exc is None:
            sys.exit("ERROR: exception event without exception type")
        nxt = events[i + 1][0] if i + 1 < len(events) else None
        if nxt == "line":
            caught.add(qualify(exc))
        elif nxt not in ("return", "exception"):
            sys.exit(f"ERROR: unexpected event after exception: {nxt}")
    if n_exc == 0:
        sys.exit("ERROR: no exception events for target function")
    if not caught:
        sys.exit("ERROR: no caught exceptions found")

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": sorted(caught)},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
