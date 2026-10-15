#!/usr/bin/env python
"""Trace -> oracle.json for debug_generate_m5_exceptions (M5_Exceptions)."""

import argparse
import builtins
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_QUALNAME = "werkzeug.debug.get_machine_id.<locals>._generate"
TARGET_FILE = "src/werkzeug/debug/__init__.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

# Non-builtin exception classes that can appear in this scenario, resolved
# to their module.QualName spelling.
NON_BUILTIN = {
    cls.__name__: f"{cls.__module__}.{cls.__qualname__}"
    for cls in (io.UnsupportedOperation,)
}

QUESTION = (
    "Run the whole test class `MachineIdProbeTest` in "
    "`werkzeug_qa/debug_generate_m5_exceptions/files/testcase.py` (all of its "
    "test methods, e.g. pytest id "
    "`werkzeug_qa/debug_generate_m5_exceptions/files/testcase.py::MachineIdProbeTest::test_plain_linux_host`). "
    "The tests reach the nested function `_generate`, defined inside `get_machine_id` in "
    "`src/werkzeug/debug/__init__.py` (qualname `werkzeug.debug.get_machine_id.<locals>._generate`), "
    "only indirectly through `werkzeug.debug.get_pin_and_cookie_name`. "
    "Across ALL invocations of `_generate` in ALL test methods of the class (an invocation is one call "
    "of the function; every simulated host triggers a fresh one), count how many times each exception "
    "type is observed in the `_generate` frame.\n\n"
    "Observation rule: an exception is observed once each time it is raised by a statement executing "
    "in the `_generate` frame or propagates into the `_generate` frame out of a function that "
    "`_generate` called (directly or through deeper callees, e.g. an error raised deep inside a call "
    "made on one of its lines counts once, in `_generate`). This holds whether the exception is then "
    "caught by one of `_generate`'s own `except` clauses or escapes `_generate` and ends the "
    "invocation. The same exception object leaving a `with` block in `_generate` (after the context "
    "manager's `__exit__` declines to suppress it) is NOT counted again, and nothing is re-raised "
    "explicitly. Exceptions that are raised and fully handled inside a callee without ever reaching "
    "the `_generate` frame do not count, and exceptions raised in other frames (including the test's "
    "own helpers, `get_machine_id`, or `get_pin_and_cookie_name`) are only counted if they propagate "
    "into `_generate`. Counts are totals over every observation in the run, so the same type observed "
    "in several invocations or test methods contributes once per observation.\n\n"
    "Naming: use bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError`, never "
    "`builtins.ValueError`) and `module.QualName` (i.e. `type(exc).__module__ + '.' + "
    "type(exc).__qualname__`) for all others (e.g. `json.decoder.JSONDecodeError`). Use the exact "
    "class of the exception instance, not a base class it is caught as.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts` whose value is a list of "
    "objects `{\"exception_type\": <str>, \"count\": <int>}`, one per exception type observed at "
    "least once (types with zero observations are omitted; each type appears exactly once). `count` "
    "is a JSON integer. Sort the list by `exception_type` ascending using plain code-point string "
    "comparison (types are unique, so no further tie-break is needed)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def type_name(name):
    if name in NON_BUILTIN:
        return NON_BUILTIN[name]
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    fail(f"cannot resolve exception type name {name!r} to module.QualName")


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
        fail(f"trace log empty: {path}")

    counts = Counter()
    calls = 0
    events = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_FILE):
            continue
        events += 1
        ev = m.group("event")
        if ev == "call":
            calls += 1
        elif ev == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                fail(f"unparseable exception event: {raw[:200]}")
            counts[type_name(em.group("name"))] += 1

    if events == 0 or calls == 0:
        fail("no trace events for the target function")
    if not counts:
        fail("no exception events observed for the target function")

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
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(answer, indent=2, sort_keys=True))
    print(f"invocations={calls} target_events={events}")


if __name__ == "__main__":
    main()
