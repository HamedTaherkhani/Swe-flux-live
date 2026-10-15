#!/usr/bin/env python
"""Harvest the S5_Exceptions oracle for Tuple._deserialize from a line trace.

Answer: the exception that propagates out of invocation 1 (the first `call`)
of marshmallow.fields.Tuple._deserialize, as type name + exact str(exc).
"""

from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import json
import re
import sys

TARGET_QUALNAME = "marshmallow.fields.Tuple._deserialize"
TRACE_REPR_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][\w]*): (?P<repr>.*) locals=\{.*\}$")
RET_RE = re.compile(r"^ retval=(?P<retval>.*?) locals=\{.*\}$")

QUESTION = (
    "Consider the test "
    "`marshmallow_qa/fields_deserialize_s5_exceptions/files/testcase.py::"
    "TupleRecordSchemaTest::test_load_record_with_mixed_slots` (test file "
    "`marshmallow_qa/fields_deserialize_s5_exceptions/files/testcase.py`, test class "
    "`TupleRecordSchemaTest`, its single test method "
    "`test_load_record_with_mixed_slots`). During this test run the method "
    "`marshmallow.fields.Tuple._deserialize` (defined in `src/marshmallow/fields.py`) "
    "is invoked several times, including recursively for nested tuple fields. An "
    "invocation is one call of that method during the test run; invocations are "
    "numbered 1, 2, 3, ... in chronological order of when the call starts (so the "
    "outer call is numbered before any calls it triggers). Invocation 1 does not "
    "return normally: an exception propagates out of it to its caller. Report that "
    "propagated exception (the exception object that actually leaves invocation 1, "
    "not any exception raised and caught inside it or inside nested invocations).\n"
    "Answer as a JSON object with exactly two string keys:\n"
    "- `exception_type`: the exception's type name. Use bare `type(exc).__name__` "
    "for built-in exceptions (e.g. `ValueError`, never `builtins.ValueError`) and "
    "`module.QualName` for all others, where module is `type(exc).__module__` and "
    "QualName is `type(exc).__qualname__` (e.g. `haystack.core.errors.PipelineError`).\n"
    "- `exception_message`: exactly `str(exc)` of that exception object, character "
    "for character (Python's own str() output, including any Python-style quoting, "
    "brackets and spacing it produces; not JSON-reformatted, no truncation)."
)

TEMPLATE = {"exception_message": "str", "exception_type": "str"}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_type_name(bare: str) -> str:
    if isinstance(getattr(builtins, bare, None), type) and issubclass(
        getattr(builtins, bare), BaseException
    ):
        return bare
    for modname in ("marshmallow.exceptions", "marshmallow"):
        mod = importlib.import_module(modname)
        cls = getattr(mod, bare, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return f"{cls.__module__}.{cls.__qualname__}"
    fail(f"cannot resolve exception type name {bare!r}")
    return ""


def message_from_repr(type_name: str, exc_repr: str) -> str:
    if len(exc_repr) > TRACE_REPR_LIMIT:
        fail("exception repr was truncated in the trace; cannot recover str(exc)")
    prefix = type_name + "("
    if not (exc_repr.startswith(prefix) and exc_repr.endswith(")")):
        fail(f"unexpected exception repr: {exc_repr!r}")
    inner = exc_repr[len(prefix) : -1]
    try:
        args = ast.literal_eval("(" + inner + ",)") if inner else ()
    except Exception as e:  # noqa: BLE001
        fail(f"cannot literal_eval exception args {inner!r}: {e}")
    if len(args) == 0:
        return ""
    if len(args) == 1:
        return str(args[0])
    return str(tuple(args))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ns = ap.parse_args()

    try:
        with open(ns.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {ns.trace_log}")
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        events.append(m.groupdict())
    if not events:
        fail(f"no events for {TARGET_QUALNAME} in trace")

    # Walk frames with a call/return stack; collect events of invocation 1.
    depth = 0
    first_events = []
    first_done = False
    for ev in events:
        kind = ev["event"]
        if kind == "call":
            depth += 1
        if depth == 1 and not first_done:
            first_events.append(ev)
        if kind == "return":
            depth -= 1
            if depth == 0:
                first_done = True
        if depth < 0:
            fail("unbalanced call/return events")
    if not first_events or first_events[0]["event"] != "call":
        fail("invocation 1 not found")
    if first_events[-1]["event"] != "return":
        fail("invocation 1 did not finish")

    ret = RET_RE.match(first_events[-1]["rest"])
    if not ret or ret.group("retval") != "None":
        fail("invocation 1 appears to return normally; no propagated exception")
    exc_events = [e for e in first_events if e["event"] == "exception"]
    if not exc_events:
        fail("no exception events in invocation 1")
    last = exc_events[-1]
    # The last exception event must be on the final executed line (propagation).
    if last["lineno"] != first_events[-1]["lineno"]:
        fail("last exception in invocation 1 was not the one propagated")
    em = EXC_RE.match(last["rest"])
    if not em:
        fail(f"cannot parse exception event: {last['rest'][:200]!r}")
    bare = em.group("name")
    answer = {
        "exception_message": message_from_repr(bare, em.group("repr")),
        "exception_type": resolve_type_name(bare),
    }

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    with open(ns.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
