#!/usr/bin/env python3
"""Parse trace logs for tests_test_iterable_s5_exceptions (S5_Exceptions)."""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/tests.py"
TARGET_FUNC = "jinja2.tests.test_iterable"
TESTCASE_MODULE = "testcase"

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)

BUILTIN_EXCEPTION_NAMES = {
    name
    for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
}


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_locals(raw_locals: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        _fail(f"unable to parse locals dict: {raw_locals!r} ({exc})")
    if not isinstance(parsed, dict):
        _fail(f"locals payload is not a dict: {raw_locals!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _parse_trace_line(raw_line: str) -> dict[str, object] | None:
    if raw_line.startswith("[TRACE]"):
        return None
    match = TRACE_LINE_RE.match(raw_line.strip())
    if not match:
        return None
    return {
        "file": _normalize_file(match.group("file")),
        "lineno": int(match.group("lineno")),
        "func": match.group("func"),
        "event": match.group("event"),
        "exc": match.group("exc"),
        "locals": _parse_locals(match.group("locals")),
    }


def _load_target_events(trace_log: Path) -> list[dict[str, object]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["file"] == TARGET_FILE and parsed["func"] == TARGET_FUNC:
            events.append(parsed)

    if not events:
        _fail(
            f"no trace events for {TARGET_FUNC} in {TARGET_FILE}; "
            f"check TRACE_FILE/TRACE_FUNC configuration"
        )
    return events


def _extract_exception_type_name(exc_field: str) -> str:
    if not exc_field:
        _fail("exception event missing exc= payload")
    name = exc_field.split(":", 1)[0].strip()
    if not name:
        _fail(f"unable to parse exception type from exc payload: {exc_field!r}")
    return name


def _format_exception_type_name(raw_name: str) -> str:
    if raw_name in BUILTIN_EXCEPTION_NAMES:
        return raw_name
    return f"{TESTCASE_MODULE}.{raw_name}"


def _caught_exception_kinds(events: list[dict[str, object]]) -> list[str]:
    caught: set[str] = set()
    in_invocation = False
    pending_raw_name: str | None = None

    for event in events:
        kind = str(event["event"])

        if kind == "call":
            in_invocation = True
            pending_raw_name = None
            continue

        if not in_invocation:
            continue

        if kind == "exception":
            pending_raw_name = _extract_exception_type_name(str(event["exc"]))
            continue

        if kind == "line":
            if pending_raw_name is not None:
                caught.add(_format_exception_type_name(pending_raw_name))
                pending_raw_name = None
            continue

        if kind == "return":
            in_invocation = False
            pending_raw_name = None

    if not caught:
        _fail(
            f"no caught exceptions recorded for {TARGET_FUNC}; "
            f"expected at least one handled exception event"
        )

    return sorted(caught)


def _build_question() -> str:
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/tests_test_iterable_s5_exceptions/files/testcase.py::"
        "TestsTestIterableS5ExceptionsTest::"
        "test_iterable_caught_exception_survey` (test class "
        "`TestsTestIterableS5ExceptionsTest`, test method "
        "`test_iterable_caught_exception_survey`). "
        "During that single test run, the function `jinja2.tests.test_iterable` "
        "in `src/jinja2/tests.py` is invoked many times. An invocation is one "
        "`call` of that function during the test run, counted in chronological "
        "order starting at 1. "
        "Report the set of exception types caught inside that function across "
        "all invocations during this test run. An exception is counted as "
        "caught when, during some invocation, an exception is raised while "
        "executing the function body and execution subsequently continues in "
        "an `except` handler in the same function frame before that "
        "invocation returns normally (equivalently: the exception does not "
        "propagate out to the caller). Do not include exceptions that "
        "propagate out of the function. "
        "Exception type naming uses bare `type(exc).__name__` for built-in "
        "exceptions (for example `ValueError`, never `builtins.ValueError`) "
        "and `module.QualName` for all others (for example "
        "`haystack.core.errors.PipelineError`). For any non-built-in "
        "exception type defined in the test module `testcase`, report it as "
        "`testcase.` followed by `type(exc).__qualname__` (for example "
        "`testcase.DynamicCollision`). "
        "Return a JSON object with exactly one key, `caught_exception_kinds`, "
        "whose value is a JSON array of strings containing each distinct "
        "caught exception type name. Sort the array ascending in ASCII order "
        "by the full type-name string; remove duplicates."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _load_target_events(args.trace_log)
    caught_exception_kinds = _caught_exception_kinds(events)

    oracle_answer = {"caught_exception_kinds": caught_exception_kinds}
    payload = {
        "question_kind": "S5_Exceptions",
        "question": _build_question(),
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
