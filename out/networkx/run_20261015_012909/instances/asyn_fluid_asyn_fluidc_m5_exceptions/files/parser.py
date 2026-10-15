"""Derive the M5_Exceptions oracle for asyn_fluidc from the trace log."""

import argparse
import builtins
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_QUALNAME = "networkx.algorithms.community.asyn_fluid.asyn_fluidc"
TARGET_FILE = "networkx/algorithms/community/asyn_fluid.py"
TEST_FILE = "networkx_qa/asyn_fluid_asyn_fluidc_m5_exceptions/files/testcase.py"
TEST_CLASS = "TestAsynFluidcScenarios"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)
EXC_RE = re.compile(r"^exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    f"Consider running ALL test methods of the pytest class `{TEST_CLASS}` in "
    f"`{TEST_FILE}` (i.e. `pytest {TEST_FILE}::{TEST_CLASS}`; every `test_*` "
    "method in the class runs, and the answer aggregates over all of them). "
    "The target is the function "
    f"`{TARGET_QUALNAME}` defined in `{TARGET_FILE}` (the body of `def "
    "asyn_fluidc(G, k, max_iter=100, seed=None)` itself, not its decorator "
    "wrappers such as `not_implemented_for`, `py_random_state` or the "
    "`_dispatchable` dispatcher, and not any callee). "
    "An invocation is one execution of that function's own frame. "
    "Count every exception OBSERVED in the target's own frame across every "
    "invocation in every test method. An exception is observed in the "
    "target frame each time it is raised by code executing in that frame "
    "(an explicit `raise` statement, or a failing operation such as a dict "
    "subscript or comparison evaluated directly in that frame) or propagates "
    "into that frame out of a callee; each such occurrence counts once, "
    "regardless of whether a `try/except` in the target frame then catches "
    "and swallows it or it continues propagating out to the caller. "
    "Exceptions raised and fully handled inside a callee (never reaching the "
    "target frame) do NOT count, nor do exceptions raised by the decorator "
    "wrappers before the target frame is entered. (The target contains no "
    "bare re-raise; a single exception object propagating through the frame "
    "counts once.) Lines inside the list comprehension of the target count "
    "as the target frame. "
    "Answer as a JSON object with a single key `exception_type_counts`, "
    "whose value is a list of objects, each with exactly two keys: "
    "`exception_type` (string) and `count` (integer, the total number of "
    "observations of that type summed over all invocations and all test "
    "methods; the same type raised in five different methods contributes "
    "five). Include every type observed at least once and no other type. "
    "`exception_type` naming convention: use the bare `type(exc).__name__` "
    "for built-in exceptions (e.g. `IndexError`, never `builtins.IndexError`), "
    "and `module.QualName` built from `type(exc).__module__` and "
    "`type(exc).__qualname__` for any non-built-in exception (e.g. "
    "`networkx.exception.NodeNotFound`). Use the exact class of the "
    "exception object, not a base class. Sort the list by `exception_type` "
    "ascending (plain Python string ordering, case-sensitive); type names "
    "are unique in the list so no further tie-break is needed."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def qualify(name):
    bobj = getattr(builtins, name, None)
    if isinstance(bobj, type) and issubclass(bobj, BaseException):
        return name
    import networkx.exception as nxe

    obj = getattr(nxe, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return f"{obj.__module__}.{obj.__qualname__}"
    fail(f"cannot resolve module of exception type {name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    counts = Counter()
    n_target_events = 0
    n_calls = 0
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        n_target_events += 1
        ev = m.group("event")
        if ev == "call":
            n_calls += 1
        elif ev == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                fail(f"malformed exception event: {raw[:200]}")
            counts[qualify(em.group("name"))] += 1

    if n_target_events == 0 or n_calls == 0:
        fail("no events for the target function in the trace")
    if not counts:
        fail("no exception events observed in the target frame")

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
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(answer, indent=2, sort_keys=True))
    print(f"target invocations: {n_calls}, target events: {n_target_events}")


if __name__ == "__main__":
    main()
