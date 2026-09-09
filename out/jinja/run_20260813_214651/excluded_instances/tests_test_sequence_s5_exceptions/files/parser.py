#!/usr/bin/env python3
"""Parse trace logs for jinja2.tests.test_sequence caught exception kinds."""

from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/tests.py"
TARGET_FUNC = "jinja2.tests.test_sequence"

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)
EXC_RE = re.compile(r"exc=(?P<exc>[^:]+)(?:: (?P<msg>.*))?\s+locals=")


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _resolve_exception_type(class_name: str) -> str:
    obj = getattr(builtins, class_name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return class_name

    tests = importlib.import_module("jinja2.tests")
    obj = getattr(tests, class_name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return f"jinja2.tests.{class_name}"

    raise SystemExit(f"Could not resolve exception class name: {class_name}")


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def _parse_exception_name(exc_field: str) -> str:
    class_name = exc_field.strip()
    if not class_name:
        raise SystemExit("Empty exception class name in trace event")
    return _resolve_exception_type(class_name)


def harvest_caught_exception_kinds(trace_log: Path) -> list[str]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    kinds: set[str] = set()
    target_events = 0
    exception_events = 0

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        if parsed["event"] != "exception":
            continue

        exception_events += 1
        exc_match = EXC_RE.search(raw_line)
        if exc_match is None:
            raise SystemExit(f"Malformed exception trace line: {raw_line}")

        kinds.add(_parse_exception_name(exc_match.group("exc")))

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if exception_events == 0:
        raise SystemExit(
            f"Trace contains {target_events} target events but zero exception events"
        )

    if not kinds:
        raise SystemExit("No caught exception kinds harvested from trace")

    return sorted(kinds)


def build_question() -> str:
    return (
        "Consider the single test method "
        "`jinja_qa/tests_test_sequence_s5_exceptions/files/testcase.py::"
        "TestSequenceCaughtExceptions::test_sequence_caught_exception_kinds`.\n\n"
        "That test calls `jinja2.tests.test_sequence` **directly** (imported "
        "from `jinja2.tests`) on many programmatically built probe values.\n\n"
        "Target function: `jinja2.tests.test_sequence` "
        f"(the function whose `def` begins at line 167 of `{TARGET_FILE}`).\n\n"
        "**Exception type naming** uses bare `type(exc).__name__` for built-in "
        "exceptions (for example `ZeroDivisionError`, never "
        "`builtins.ZeroDivisionError`) and `module.QualName` for all other "
        "exception classes (for example `jinja2.exceptions.TemplateError`).\n\n"
        "**Caught-exception rule**: an exception type is counted if, during "
        "the test run, Python records an `exception` trace event in a frame "
        f"whose qualname is `{TARGET_FUNC}` and whose code object is defined "
        f"in `{TARGET_FILE}`, and that exception is subsequently handled inside "
        "the target function by the `except Exception` clause that begins at "
        "line 174 rather than propagating out of the target function. Each "
        "distinct exception **type** (not each individual raise) contributes "
        "one entry. Re-raises of the same type after a catch still count only "
        "once toward the set because the answer is a set of types.\n\n"
        "**Exclusions**: exception events in callee frames (for example inside "
        "`len` or attribute lookup helpers) do not count unless the "
        "corresponding `exception` event is also observed in the "
        f"`{TARGET_FUNC}` frame as described above. Exceptions raised in the "
        "target frame that are not handled inside the target function do not "
        "count; this scenario does not occur in the assigned test.\n\n"
        "Return JSON with exactly one top-level key `caught_exception_kinds`: "
        "a list of strings naming every exception type caught at least once, "
        "sorted ascending by the string value (Unicode code-point order). "
        "Include no duplicates."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    kinds = harvest_caught_exception_kinds(args.trace_log)

    oracle_answer = {"caught_exception_kinds": kinds}
    template_answer = {"caught_exception_kinds": ["str"]}

    payload = {
        "question_kind": "S5_Exceptions",
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
