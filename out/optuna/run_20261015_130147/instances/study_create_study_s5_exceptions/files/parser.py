#!/usr/bin/env python
"""Trace -> oracle for study_create_study_s5_exceptions.

Finds the first invocation of optuna.study.study.create_study whose frame
terminated by exception propagation (return event with retval=None, since the
function otherwise always returns a Study), and reports the type and str() of
the last exception event recorded in that frame (the one that escaped).
"""
from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "optuna.study.study.create_study"
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)
SEARCH_MODULES = ["optuna.exceptions", "optuna.study.study", "optuna.storages"]

QUESTION = (
    "Consider the pytest test "
    "`optuna_qa/study_create_study_s5_exceptions/files/testcase.py::CreateStudyEscapeTest::"
    "test_first_escaping_error` (file `optuna_qa/study_create_study_s5_exceptions/files/testcase.py`, "
    "class `CreateStudyEscapeTest`, single test method `test_first_escaping_error`). The test "
    "calls the function `optuna.study.study.create_study` (defined in `optuna/study/study.py`) "
    "repeatedly with seeded, programmatically generated arguments until one call raises. "
    "An invocation is one call of `create_study` during this test run, numbered 1-based in "
    "chronological order. Exceptions raised and caught inside `create_study` itself (i.e. handled "
    "by its own `except` clause without leaving the function) do NOT count; we care only about "
    "the exception object that propagates OUT of `create_study` to its caller in the FIRST "
    "invocation that does not return normally. Report that exception as a JSON object with "
    "exactly two string keys: `exception_type` and `exception_message`. "
    "`exception_type` naming convention: use the bare `type(exc).__name__` for built-in "
    "exceptions (e.g. `KeyError`, never `builtins.KeyError`), and `module.QualName` for all "
    "others, where `module` is the class's `__module__` and `QualName` its `__qualname__` "
    "(e.g. `json.decoder.JSONDecodeError`). "
    "`exception_message` is exactly `str(exc)` of the propagated exception, character for "
    "character (any newline characters it contains are kept as real newlines, i.e. `\\n` in the "
    "JSON encoding; no surrounding quotes, no type prefix)."
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_type_name(short: str) -> str:
    obj = getattr(builtins, short, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return short
    for mod_name in SEARCH_MODULES:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, short, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return f"{cls.__module__}.{cls.__qualname__}"
    fail(f"cannot resolve exception type {short!r}")
    return ""


def parse_message(short: str, exc_repr: str) -> str:
    try:
        node = ast.parse(exc_repr, mode="eval").body
    except SyntaxError:
        fail(f"cannot parse exception repr (possibly truncated): {exc_repr!r}")
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == short):
        fail(f"unexpected exception repr shape: {exc_repr!r}")
    args = [ast.literal_eval(a) for a in node.args]
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

    path = Path(ns.trace_log)
    if not path.is_file() or path.stat().st_size == 0:
        fail(f"trace log missing or empty: {path}")

    events = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = EVENT_RE.match(raw)
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        events.append(m.groupdict())
    if not events:
        fail("no events for target function in trace")

    invocations: list[list[dict]] = []
    current = None
    for ev in events:
        if ev["event"] == "call":
            current = []
            invocations.append(current)
        if current is None:
            fail("event before first call")
        current.append(ev)
        if ev["event"] == "return":
            current = None

    answer = None
    for inv in invocations:
        ret = [e for e in inv if e["event"] == "return"]
        if not ret:
            fail("invocation without return event")
        if not ret[-1]["rest"].startswith("retval=None "):
            continue
        excs = [e for e in inv if e["event"] == "exception"]
        if not excs:
            fail("propagating invocation without exception event")
        rest = excs[-1]["rest"]
        if not rest.startswith("exc="):
            fail(f"malformed exception event: {rest!r}")
        body = rest[len("exc="):].rsplit(" locals=", 1)[0]
        short, _, exc_repr = body.partition(": ")
        answer = {
            "exception_message": parse_message(short, exc_repr),
            "exception_type": resolve_type_name(short),
        }
        break
    if answer is None:
        fail("no invocation propagated an exception")

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": answer,
    }
    Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
    Path(ns.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
