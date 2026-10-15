#!/usr/bin/env python
"""Parse the get_class trace: exception propagated by the last raising invocation
that did not catch anything inside get_class."""

import argparse
import ast
import builtins
import importlib
import json
import re
import sys

TARGET_FUNC = "marshmallow.class_registry.get_class"
TARGET_FILE_SUFFIX = "src/marshmallow/class_registry.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_.]*): (?P<repr>.*) locals=\{.*\}$")
RET_RE = re.compile(r"^ retval=(?P<retval>.*?) locals=\{.*\}$")

QUESTION = (
    "Run the single test "
    "`marshmallow_qa/class_registry_get_class_s5_exceptions/files/testcase.py::"
    "TestGetClassExceptions::test_lookup_storm` (test class `TestGetClassExceptions`, "
    "file `marshmallow_qa/class_registry_get_class_s5_exceptions/files/testcase.py`) with "
    "pytest. The target function is `marshmallow.class_registry.get_class`, defined in "
    "`src/marshmallow/class_registry.py`.\n\n"
    "An invocation is one call of `get_class` during the test run; invocations are numbered "
    "1, 2, 3, ... in chronological order. An invocation 'propagated an exception' if it did "
    "not return normally, i.e. an exception left the `get_class` frame and reached its caller "
    "(the test's `try`). An exception is 'caught inside' an invocation if it was raised in "
    "that `get_class` frame and handled by an `except` clause of `get_class` itself.\n\n"
    "Among all invocations that propagated an exception AND in which no exception at all was "
    "caught inside `get_class`, select the one with the HIGHEST invocation number. Report "
    "the exception object that propagated out of that invocation (the object itself, not its "
    "`__cause__` or `__context__`).\n\n"
    "Answer format: a JSON object with exactly two string keys: `exception_type` and "
    "`exception_message`. `exception_type` naming: use the bare `type(exc).__name__` for "
    "built-in exception types (e.g. `ValueError`, never `builtins.ValueError`) and "
    "`module.QualName` for every other exception type, where `module` is the class's "
    "`__module__` and `QualName` its `__qualname__` (e.g. "
    "`json.decoder.JSONDecodeError`). Report the concrete type of the object, not a base "
    "class. `exception_message` is exactly `str(exc)`, character for character (no type "
    "prefix, no surrounding quotes added, quotes inside the message kept as they appear)."
)

TEMPLATE = {"exception_message": "str", "exception_type": "str"}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def type_label(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    # Non-builtin: resolve within marshmallow.exceptions (the only exception module
    # get_class raises from).
    mod = importlib.import_module("marshmallow.exceptions")
    cls = getattr(mod, name, None)
    if not (isinstance(cls, type) and issubclass(cls, BaseException)):
        fail(f"cannot resolve exception type {name!r}")
    return f"{cls.__module__}.{cls.__qualname__}"


def message_from_repr(exc_repr):
    try:
        node = ast.parse(exc_repr, mode="eval").body
    except SyntaxError:
        fail(f"cannot parse exception repr {exc_repr!r}")
    if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
        fail(f"unexpected exception repr shape {exc_repr!r}")
    arg = ast.literal_eval(node.args[0])
    return str(arg)


def main():
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

    invocations = []
    cur = None
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC or not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        ev = m.group("event")
        rest = m.group("rest")
        if ev == "call":
            if cur is not None:
                fail("nested/unterminated get_class invocation in trace")
            cur = {"events": []}
            continue
        if cur is None:
            fail("event outside of an invocation")
        if ev == "exception":
            em = EXC_RE.match(rest)
            if not em:
                fail(f"cannot parse exception event: {raw}")
            cur["events"].append(("exception", em.group("name"), em.group("repr")))
        elif ev == "line":
            cur["events"].append(("line",))
        elif ev == "return":
            rm = RET_RE.match(rest)
            if not rm:
                fail(f"cannot parse return event: {raw}")
            cur["retval"] = rm.group("retval")
            invocations.append(cur)
            cur = None
    if cur is not None:
        fail("trace ended inside an invocation")
    if not invocations:
        fail("zero get_class invocations in trace")

    selected = None
    for idx, inv in enumerate(invocations, start=1):
        evs = inv["events"]
        # Propagated: last event before return is an exception event, retval None.
        if not evs or evs[-1][0] != "exception" or inv["retval"] != "None":
            continue
        exc_events = [e for e in evs if e[0] == "exception"]
        # Any exception event other than the propagated one was caught inside the frame
        # (execution continued afterwards in the same frame).
        caught_inside = len(exc_events) > 1
        if caught_inside:
            continue
        selected = (idx, evs[-1])
    if selected is None:
        fail("no invocation matched the selection rule")

    _idx, (_, name, exc_repr) = selected
    answer = {
        "exception_message": message_from_repr(exc_repr),
        "exception_type": type_label(name),
    }
    out = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
