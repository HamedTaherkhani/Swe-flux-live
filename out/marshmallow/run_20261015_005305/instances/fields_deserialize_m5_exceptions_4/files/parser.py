#!/usr/bin/env python
"""Trace -> oracle.json for fields_deserialize_m5_exceptions_4 (M5_Exceptions)."""

from __future__ import annotations

import argparse
import builtins
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_QUALNAME = "marshmallow.fields.Boolean._deserialize"
TARGET_FILE_SUFFIX = "src/marshmallow/fields.py"
NON_BUILTIN_MODULES = ["marshmallow.exceptions"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    "Consider the test class `TestBooleanDeserializeExceptions` in "
    "`marshmallow_qa/fields_deserialize_m5_exceptions_4/files/testcase.py`, run with "
    "`pytest marshmallow_qa/fields_deserialize_m5_exceptions_4/files/testcase.py::TestBooleanDeserializeExceptions` "
    "(all 13 of its test methods, aggregated together; method order does not matter for the answer). "
    "Focus on the method `marshmallow.fields.Boolean._deserialize` defined in `src/marshmallow/fields.py` "
    "(the `_deserialize` method of class `Boolean`; NOT any other field class's `_deserialize`). "
    "Across ALL invocations of that method (an invocation = one call of the method) during ALL test methods "
    "of the class, count how many times each exception type is observed in the `Boolean._deserialize` frame.\n\n"
    "Observation rule: an exception is observed in the frame when it is raised by code executing in that exact "
    "frame (e.g. a `raise` statement in the method body, or a failing built-in operation such as a set "
    "membership test or `bool(...)` evaluated on one of the method's lines), OR when it propagates into that "
    "frame out of a callee (e.g. escaping `self.make_error(...)`, or escaping a user-defined `__hash__`, "
    "`__eq__`, `__bool__` or `__str__` that the frame's own operations invoke). Each such event counts once "
    "per frame invocation per exception: an exception that arrives in the frame and is then caught by the "
    "`except` clause in the frame counts once; an exception that arrives and is not caught (so it continues to "
    "propagate out of the method) also counts exactly once (leaving the frame does not count again). A new "
    "exception raised or propagated while executing inside the `except` handler (e.g. via `raise ... from "
    "error`, or one escaping the `make_error` call there) is a separate observation of its own type, in "
    "addition to the one that was caught. A bare re-raise of the same exception object in the same frame would "
    "count again, but this method's code never does that. Exceptions raised AND fully handled inside a callee "
    "(never escaping the callee into the `Boolean._deserialize` frame) do NOT count. Exceptions in other frames "
    "(the test methods, the `drive` helper, or the helper classes' dunder methods themselves) do NOT count on "
    "their own. Counts are totals over all invocations and all test methods: the same type observed in five "
    "different invocations contributes five.\n\n"
    "Naming: use bare `type(exc).__name__` for built-in exception classes (e.g. `ArithmeticError`, never "
    "`builtins.ArithmeticError`), and `module.QualName` (i.e. `f\"{type(exc).__module__}.{type(exc).__qualname__}\"`, "
    "e.g. `json.decoder.JSONDecodeError`) for every non-built-in exception class.\n\n"
    "Answer format: a JSON object with a single key `exception_type_counts`, whose value is a list of objects "
    "`{\"count\": <int>, \"exception_type\": <str>}`, one per exception type observed at least once (types never "
    "observed are omitted; no entry has count 0). Sort the list by `exception_type` ascending (plain Python "
    "string ordering, case-sensitive); since each type appears exactly once, there are no ties."
)

TEMPLATE = {"exception_type_counts": [{"count": "int", "exception_type": "str"}]}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def qualify(name: str) -> str:
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    for modname in NON_BUILTIN_MODULES:
        mod = __import__(modname, fromlist=["_"])
        cls = getattr(mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return f"{cls.__module__}.{cls.__qualname__}"
    fail(f"cannot resolve exception class name {name!r}")
    return ""  # unreachable


def main() -> None:
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

    calls = 0
    lines = 0
    distinct_lines: set[int] = set()
    counts: Counter[str] = Counter()
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if m["func"] != TARGET_QUALNAME or not m["file"].endswith(TARGET_FILE_SUFFIX):
            continue
        event = m["event"]
        if event == "call":
            calls += 1
        elif event == "line":
            lines += 1
            distinct_lines.add(int(m["lineno"]))
        elif event == "exception":
            em = EXC_RE.match(m["rest"])
            if not em:
                fail(f"unparseable exception event: {raw}")
            counts[qualify(em["name"])] += 1

    if calls == 0:
        fail("zero call events for target function in trace")
    if not counts:
        fail("no exception events for target function in trace")

    answer = {
        "exception_type_counts": [
            {"count": counts[name], "exception_type": name} for name in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"calls={calls} line_events={lines} distinct_lines={len(distinct_lines)} "
        f"exception_events={sum(counts.values())}"
    )
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
