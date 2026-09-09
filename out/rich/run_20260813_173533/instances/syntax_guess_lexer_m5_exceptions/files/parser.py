#!/usr/bin/env python3
"""Parse trace log into M5_Exceptions oracle for Syntax.guess_lexer."""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
from pathlib import Path

TARGET_FILE = "rich/syntax.py"
TARGET_FUNC = "rich.syntax.Syntax.guess_lexer"

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)

BUILTIN_EXCEPTION_NAMES = {
    name
    for name in dir(builtins)
    if name.endswith("Error") or name.endswith("Exception") or name == "StopIteration"
}

# Non-builtin exception types that can propagate into guess_lexer from callees.
NON_BUILTIN_EXCEPTION_TYPES: dict[str, str] = {
    "ClassNotFound": "pygments.util.ClassNotFound",
}


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_locals(raw: str) -> dict[str, str]:
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"locals is not a dict: {raw!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _format_exception_type(exc_name: str) -> str:
    if exc_name in BUILTIN_EXCEPTION_NAMES:
        return exc_name
    if exc_name in NON_BUILTIN_EXCEPTION_TYPES:
        return NON_BUILTIN_EXCEPTION_TYPES[exc_name]
    raise SystemExit(
        f"Unmapped non-builtin exception type in trace: {exc_name!r}"
    )


def _parse_exception_type(exc_field: str) -> str:
    if not exc_field:
        raise ValueError("empty exc field")
    exc_name = exc_field.split(":", 1)[0].strip()
    return _format_exception_type(exc_name)


def _parse_trace_events(trace_log: Path) -> list[dict]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    events: list[dict] = []
    for line in text.splitlines():
        if TARGET_FUNC not in line:
            continue
        match = LINE_EVENT_RE.match(line)
        if not match:
            continue
        file_path = _normalize_path(match.group("file"))
        if file_path != TARGET_FILE:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        event = {
            "lineno": int(match.group("lineno")),
            "event": match.group("event"),
            "exc": match.group("exc"),
            "locals": _parse_locals(match.group("locals")),
        }
        events.append(event)

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )
    return events


def _compute_exception_type_counts(events: list[dict]) -> list[dict[str, int | str]]:
    counts: dict[str, int] = {}
    exception_events = [event for event in events if event["event"] == "exception"]
    if not exception_events:
        raise SystemExit("No exception events found for target function")

    for event in exception_events:
        exc_type = _parse_exception_type(event["exc"])
        counts[exc_type] = counts.get(exc_type, 0) + 1

    return [
        {"exception_type": exc_type, "count": counts[exc_type]}
        for exc_type in sorted(counts.keys())
    ]


QUESTION = """\
During pytest run of every test method in \
rich_qa/syntax_guess_lexer_m5_exceptions/files/testcase.py::TestSyntaxGuessLexerExceptions \
(test methods are executed in definition order; pytest ids look like \
rich_qa/syntax_guess_lexer_m5_exceptions/files/testcase.py::TestSyntaxGuessLexerExceptions::test_python_module_source), \
the function rich.syntax.Syntax.guess_lexer in rich/syntax.py is reached indirectly \
via rich.syntax.Syntax.from_path (the test never names guess_lexer; from_path reads \
each temp file and calls guess_lexer when no lexer argument is supplied).

Aggregate exception observations across ALL invocations of guess_lexer in that full \
run (every test method, every call inside loops, chronological order).

An exception observation counts once each time the target frame receives a sys.trace \
exception event while executing guess_lexer: the exception was raised in a callee and \
propagated into this frame before any handler in guess_lexer runs, or was raised by \
code executing in guess_lexer itself. Each distinct propagation into the frame is one \
observation even if the same exception object is later re-raised in the same frame \
(this target does not re-raise, but identical objects would still count separately). \
Exceptions raised and fully handled inside a callee without entering guess_lexer do \
not count. Exceptions caught by an except handler inside guess_lexer (for example the \
handler that passes after a failed lexer lookup) still count because they were \
observed in the frame before handling.

Report exception type names using type(exc).__name__ for built-in exceptions (e.g. \
ValueError, never builtins.ValueError) and module.QualName for all others (e.g. \
some_vendor.errors.LookupFailure). Use only the type name, not the message.

Report total per-type counts (not deduplicated across invocations): if the same type \
is observed in five separate invocations, its count includes all five.

Sort the answer list ascending by exception_type (lexicographic string order). \
Tie-break: none needed for distinct types.

Use the exception_type_counts answer shape: a JSON object with key \
exception_type_counts whose value is a list of objects each having keys \
exception_type (str) and count (int).\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 50:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 50"
        )
    distinct_lines = {event["lineno"] for event in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    exception_type_counts = _compute_exception_type_counts(events)
    oracle_answer = {"exception_type_counts": exception_type_counts}
    template_answer = {
        "exception_type_counts": [{"count": "int", "exception_type": "str"}]
    }

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
