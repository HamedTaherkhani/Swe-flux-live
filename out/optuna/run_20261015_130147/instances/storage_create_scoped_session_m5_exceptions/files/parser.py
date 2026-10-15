#!/usr/bin/env python
"""Trace -> oracle.json for storage_create_scoped_session_m5_exceptions.

Counts every ``exception`` trace event emitted inside the frame of
``optuna.storages._rdb.storage._create_scoped_session`` across the whole run,
grouped by exception type.
"""

from __future__ import annotations

import argparse
import builtins
import importlib
import json
import os
import re
import sys


TARGET_FUNC = "optuna.storages._rdb.storage._create_scoped_session"
TARGET_FILE_SUFFIX = "optuna/storages/_rdb/storage.py"
TEST_FILE = "optuna_qa/storage_create_scoped_session_m5_exceptions/files/testcase.py"
TEST_CLASS = "TestRDBStorageSessionScenarios"

# Modules searched (in order) to resolve a non-builtin exception class name
# from the bare ``__name__`` recorded in the trace.
CANDIDATE_MODULES = ["optuna.exceptions", "sqlalchemy.exc"]

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = f"""\
Consider the pytest test class `{TEST_CLASS}` in `{TEST_FILE}`. Run ALL of its test methods (the whole class, e.g. `pytest {TEST_FILE}::{TEST_CLASS}`); every method builds its own fresh in-memory SQLite `RDBStorage` instance(s), shared with no other method. The test file never calls the target directly; it is reached through `RDBStorage` / `optuna` public APIs.

Target: the generator-based context manager `optuna.storages._rdb.storage._create_scoped_session` defined in `optuna/storages/_rdb/storage.py` (decorated with `@contextmanager`). Its frame is the generator frame of that function; one generator frame exists per `with _create_scoped_session(...)` entry, and it may be suspended at `yield session` while the caller's `with` body runs.

Question: across the ENTIRE run (all invocations of the target, in all test methods of the class, totals summed), how many times was each exception type OBSERVED in the target's frame?

Observation rule (one observation = one time an exception becomes active/propagates at a line of the target frame):
- An exception raised by the caller's `with` body and thrown into the generator at the `yield session` line counts once (at that line).
- An exception propagating out of a call made directly on a line of the target frame (e.g. raised somewhere inside `session.commit()` and not handled there) counts once.
- An exception newly raised by a `raise X(...)` / `raise X(...) from e` statement in the target frame counts once (a new exception object).
- A bare `raise` that re-raises the exception currently being handled (the same exception object, in the same frame) does NOT count again.
- Exceptions raised and fully handled inside callees (never reaching the target frame), and exceptions that only exist in the callers (e.g. a caller converting an exception into another type after the context manager exits, or a caller catching what the target re-raised) do NOT count. Whether a handler in the target later swallows the exception is irrelevant: the observation still counts.
- Count every observation, not distinct invocations or distinct types: if the same type is observed five times (in any invocations/test methods), its count is 5.

Exception type naming: bare `type(exc).__name__` for built-in exceptions (e.g. `LookupError`, never `builtins.LookupError`); for every non-builtin exception use `type(exc).__module__ + "." + type(exc).__qualname__` (e.g. `optuna.exceptions.DuplicatedStudyError` style, `json.decoder.JSONDecodeError` style).

Output: a JSON object `{{"exception_type_counts": [{{"count": <int>, "exception_type": <str>}}, ...]}}` with one entry for every exception type observed at least once (types never observed are omitted; no zero counts). Sort entries by `exception_type` ascending using plain Python string ordering (code-point order, case-sensitive); type names are unique so there is no tie. `count` is a JSON integer.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def qualify(name: str) -> str:
    builtin = getattr(builtins, name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return name
    for mod_name in CANDIDATE_MODULES:
        mod = importlib.import_module(mod_name)
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

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        fail("trace log is empty")

    target_events = 0
    line_events = 0
    counts: dict[str, int] = {}
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC or not m.group("file").endswith(TARGET_FILE_SUFFIX):
            continue
        target_events += 1
        event = m.group("event")
        if event == "line":
            line_events += 1
        if event != "exception":
            continue
        em = EXC_RE.match(m.group("rest"))
        if not em:
            fail(f"unparseable exception event: {raw[:200]}")
        exc_type = qualify(em.group("name"))
        counts[exc_type] = counts.get(exc_type, 0) + 1

    if target_events == 0:
        fail("no trace events for the target function")
    if line_events == 0:
        fail("no line events for the target function")
    if not counts:
        fail("no exception events observed in the target frame")

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
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
