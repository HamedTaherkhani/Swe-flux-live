#!/usr/bin/env python3
"""Parse trace log into S5_Exceptions oracle for Color.parse."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "S5_Exceptions"
TARGET_FILE = "rich/color.py"
TARGET_FUNC = "rich.color.Color.parse"
TEST_FILE = "rich_qa/color_parse_s5_exceptions/files/testcase.py"
TEST_CLASS = "ColorParseExceptionsTest"
TEST_METHOD = "test_seeded_parse_batch_with_single_propagated_error"

QUESTION = f"""\
During the pytest run of {TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}, consider the \
function {TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line 433).

The test calls {TARGET_FUNC} many times with programmatically built color strings. \
Exactly one of those calls raises an exception that propagates out of \
{TARGET_FUNC} to the test caller without being caught inside {TARGET_FUNC}. Report \
that propagated exception (the exception object whose raise site is inside \
{TARGET_FUNC} on one of the raise statements in that function body).

Exception type naming: report bare type(exc).__name__ for built-in exceptions (for \
example ValueError, never builtins.ValueError) and module.QualName for all other \
exception classes (for example rich.color.ColorParseError). The solver must apply \
this rule exactly.

Exception message: report the exact str(exc) string, character for character, for \
that exception object (not repr(exc) and not the args tuple repr).

Report JSON with exactly these top-level keys inside oracle_answer:
- exception_type (str)
- exception_message (str)\
"""

TEMPLATE_ANSWER = {
    "exception_message": "str",
    "exception_type": "str",
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>.+?)(?= locals=|$))?"
)

LOCALS_RE = re.compile(r" locals=(?P<locals>\{.*\})$")

RAISE_LINES = {
    451: "invalid",
    463: "color8_overflow",
    473: "rgb_component_count",
    479: "rgb_component_overflow",
}


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _parse_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if not match:
        return {}
    blob = match.group("locals")
    try:
        parsed = ast.literal_eval(blob)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"unable to parse locals from trace line: {raw_line!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"locals payload is not a dict: {raw_line!r}")
    return parsed


def _unrepr(value: str) -> str:
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, str):
        raise ValueError(f"expected string local value, got {type(parsed)!r}")
    return parsed


def _format_exception_type(raw_type: str) -> str:
    if raw_type == "ColorParseError":
        return "rich.color.ColorParseError"
    if "." in raw_type:
        return raw_type
    return raw_type


def _message_from_locals(line_no: int, locals_dict: dict[str, str]) -> str:
    kind = RAISE_LINES.get(line_no)
    if kind is None:
        raise ValueError(f"unexpected raise line {line_no} in {TARGET_FILE}")

    original_color = _unrepr(locals_dict["original_color"]) if "original_color" in locals_dict else None
    color = _unrepr(locals_dict["color"]) if "color" in locals_dict else None

    if kind == "invalid":
        if original_color is None:
            raise ValueError("missing original_color local for invalid-color raise")
        return f"{original_color!r} is not a valid color"
    if kind == "color8_overflow":
        if color is None:
            raise ValueError("missing color local for color8 overflow raise")
        return f"color number must be <= 255 in {color!r}"
    if kind == "rgb_component_count":
        if original_color is None:
            raise ValueError("missing original_color local for rgb component-count raise")
        return f"expected three components in {original_color!r}"
    if kind == "rgb_component_overflow":
        if original_color is None:
            raise ValueError("missing original_color local for rgb overflow raise")
        return f"color components must be <= 255 in {original_color!r}"
    raise ValueError(f"unhandled raise kind {kind!r}")


def _find_propagated_exception(trace_log: Path) -> tuple[str, str]:
    if not trace_log.is_file():
        raise SystemExit(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_log}")

    matched_events = 0
    line_events = 0
    distinct_lines: set[int] = set()
    invocations: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        match = TRACE_LINE_RE.match(raw_line)
        if not match:
            continue

        if _normalize_file(match.group("file")) != TARGET_FILE:
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        matched_events += 1
        event = match.group("event")
        line_no = int(match.group("line"))
        locals_dict = _parse_locals(raw_line)

        if event == "call":
            current = {"locals_state": {}, "locals_history": []}
            invocations.append(current)
        elif current is None:
            continue

        if locals_dict:
            current["locals_state"].update(locals_dict)

        if event == "line":
            line_events += 1
            distinct_lines.add(line_no)
            if locals_dict:
                current["locals_history"].append((line_no, dict(locals_dict)))
        elif event == "exception":
            exc_field = match.group("exc")
            if not exc_field:
                raise ValueError(f"missing exc= field: {raw_line!r}")
            exc_type_raw = exc_field.split(":", 1)[0].strip()
            message = _message_from_locals(line_no, current["locals_state"])
            exc_type = _format_exception_type(exc_type_raw)
            current["exception"] = (exc_type, message, line_no)
        elif event == "return":
            current["returned"] = True

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if line_events < 30:
        raise SystemExit(
            f"trace log has only {line_events} line events for {TARGET_FUNC}; need >= 30"
        )

    if len(distinct_lines) < 8:
        raise SystemExit(
            f"trace log has only {len(distinct_lines)} distinct executed lines; need >= 8"
        )

    failing = [inv for inv in invocations if inv.get("exception") is not None]
    if len(failing) != 1:
        raise SystemExit(
            f"expected exactly one failing invocation, found {len(failing)}"
        )

    exc_type, message, _line = failing[0]["exception"]
    return exc_type, message


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    exc_type, exc_message = _find_propagated_exception(args.trace_log)
    oracle_answer = {
        "exception_type": exc_type,
        "exception_message": exc_message,
    }

    payload = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
