#!/usr/bin/env python
"""Trace -> oracle for file_acquire_s5_exceptions.

Collects the set of exception types caught by an ``except`` clause of
optuna.storages.journal._file.JournalFileOpenLock.acquire across all of its
invocations. An exception event in the acquire frame counts as caught when the
next event of that same frame is a ``line`` event (a handler started running);
if the next event is ``return`` the exception propagated out uncaught.
"""
from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "optuna.storages.journal._file.JournalFileOpenLock.acquire"
TARGET_FILE_SUFFIX = "optuna/storages/journal/_file.py"
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)
EXC_RE = re.compile(r"^exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")
SEARCH_MODULES = ["optuna.exceptions", "optuna.storages.journal._file"]

TEST_PATH = "optuna_qa/file_acquire_s5_exceptions/files/testcase.py"
QUESTION = (
    "Consider the pytest test "
    f"`{TEST_PATH}::JournalFileOpenLockAcquireTest::test_acquire_under_contention` "
    f"(file `{TEST_PATH}`, class `JournalFileOpenLockAcquireTest`, single test method "
    "`test_acquire_under_contention`). The test replaces the `os` and `time` modules seen by "
    "`optuna/storages/journal/_file.py` with seeded in-memory fakes and then calls "
    "`optuna.storages.journal._file.JournalFileOpenLock.acquire` (defined in "
    "`optuna/storages/journal/_file.py`) several times. An invocation is one call of that "
    "`acquire` method during the test run, numbered 1-based in chronological order; consider "
    "ALL invocations. "
    "An exception counts as CAUGHT by `acquire` when it arrives in the `acquire` frame (raised "
    "there or propagated into it from a callee such as the fake `os` functions or "
    "`self.release()`) and one of the `except` clauses written lexically inside "
    "`JournalFileOpenLock.acquire` matches it, so that the handler body starts executing. "
    "This includes exceptions that the handler later re-raises (e.g. via `raise err` or bare "
    "`raise`): the original exception still counts as caught. It does NOT include an exception "
    "raised from inside a handler body that no enclosing `except` clause of `acquire` matches "
    "(it propagates out of `acquire` to the test), nor exceptions raised and handled entirely "
    "inside other functions (e.g. inside `release` itself) that never reach the `acquire` "
    "frame. Report the set of distinct runtime types (`type(exc)`, the concrete class of the "
    "exception object, not the class named in the `except` clause) of all caught exceptions as "
    "JSON `{\"caught_exception_kinds\": [...]}`, a list of strings, each type listed once "
    "(duplicates removed), sorted in ascending plain Python string order (code-point order, so "
    "uppercase letters sort before lowercase ones). Type-naming convention: use the bare "
    "`type(exc).__name__` for built-in exceptions (e.g. `KeyError`, never `builtins.KeyError`), "
    "and `module.QualName` for all others, where `module` is the class's `__module__` and "
    "`QualName` its `__qualname__` (e.g. `json.decoder.JSONDecodeError`). Note that the "
    "concrete class of an `OSError(errno_code, ...)` object is determined by Python from the "
    "errno code."
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
    fail(f"cannot resolve exception type name {short!r}")
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {path}")

    events = []
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m["func"] != TARGET_QUALNAME or not m["file"].endswith(TARGET_FILE_SUFFIX):
            continue
        events.append((int(m["line"]), m["event"], m["rest"]))
    if not events:
        fail("no events for target function in trace")
    if not any(e[1] == "call" for e in events):
        fail("no call events for target function in trace")
    if not any(e[1] == "exception" for e in events):
        fail("no exception events for target function in trace")

    # acquire is never re-entered, so frames are delimited by call/return events.
    caught: set[str] = set()
    pending: str | None = None
    for _line, ev, rest in events:
        if ev == "call":
            if pending is not None:
                fail("unterminated exception before new call")
            continue
        if pending is not None:
            if ev == "line":
                caught.add(pending)
                pending = None
            elif ev == "return":
                pending = None
        if ev == "exception":
            m = EXC_RE.match(rest)
            if not m:
                fail(f"cannot parse exception event: {rest[:120]}")
            pending = resolve_type_name(m["name"])
    if not caught:
        fail("no caught exceptions found")

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": sorted(caught)},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
