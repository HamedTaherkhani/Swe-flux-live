#!/usr/bin/env python3
"""Parse trace logs for debug_rewrite_traceback_stack_s3_state (S3_ProgramState)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/debug.py"
TARGET_FUNC = "jinja2.debug.rewrite_traceback_stack"
OBSERVATION_LINE = 64
OBSERVATION_EXECUTION = 17
TARGET_INVOCATION = 1
REQUESTED_VARIABLES = ("exc_value", "lineno", "source", "template")

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)


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


def _observed_state(events: list[dict[str, object]]) -> list[dict[str, str]]:
    invocation = 0
    in_target = False
    execution_count = 0
    locals_state: dict[str, str] = {}

    for event in events:
        kind = str(event["event"])
        lineno = int(event["lineno"])
        changed_locals = dict(event["locals"])

        if kind == "call":
            invocation += 1
            in_target = invocation == TARGET_INVOCATION
            locals_state = dict(changed_locals)
            execution_count = 0
            continue

        if not in_target:
            continue

        if kind in ("return", "exception"):
            break

        if kind != "line":
            continue

        locals_state.update(changed_locals)

        if lineno != OBSERVATION_LINE:
            continue

        execution_count += 1
        if execution_count != OBSERVATION_EXECUTION:
            continue

        observed: list[dict[str, str]] = []
        for variable in sorted(REQUESTED_VARIABLES):
            if variable not in locals_state:
                _fail(
                    f"variable {variable!r} missing from locals at "
                    f"{TARGET_FILE}:{OBSERVATION_LINE} execution "
                    f"{OBSERVATION_EXECUTION} during invocation "
                    f"{TARGET_INVOCATION}"
                )
            observed.append(
                {"variable": variable, "value": locals_state[variable]}
            )
        return observed

    if invocation < TARGET_INVOCATION:
        _fail(
            f"trace contains only {invocation} invocation(s) of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    _fail(
        f"only {execution_count} execution(s) of line {OBSERVATION_LINE} during "
        f"invocation {TARGET_INVOCATION}; need {OBSERVATION_EXECUTION}"
    )


def _build_question() -> str:
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/debug_rewrite_traceback_stack_s3_state/files/testcase.py::"
        "RewriteTracebackStackS3StateTest::"
        "test_direct_call_rewrites_nested_include_traceback` (test class "
        "`RewriteTracebackStackS3StateTest`, test method "
        "`test_direct_call_rewrites_nested_include_traceback`). "
        "During that single test run, the function "
        "`jinja2.debug.rewrite_traceback_stack` in `src/jinja2/debug.py` is "
        "invoked. An invocation is one `call` event for that function during "
        "the test run, counted in chronological order starting at 1. "
        f"For invocation {TARGET_INVOCATION} only, consider the observation "
        f"point defined as: immediately after line {OBSERVATION_LINE} "
        "(`tb = tb.tb_next`) has finished executing for the "
        f"{OBSERVATION_EXECUTION}th time during that invocation. Count an "
        "execution of line "
        f"{OBSERVATION_LINE} as the Nth time a `line` event is recorded for "
        f"that line number while inside invocation {TARGET_INVOCATION}; line "
        "events on other lines, `call`, `return`, and `exception` events do "
        "not advance this counter. Line numbers are absolute, 1-based, and "
        "refer to `src/jinja2/debug.py` as it exists in the repository; for "
        "multi-line statements, attribute executed-line events to the line "
        "where that statement begins. "
        "Report the Python `repr()` strings of the local variables "
        "`exc_value`, `lineno`, `source`, and `template` that are in scope at "
        "that observation point. Use `repr()` for every reported value; for "
        "container objects report the `repr()` of the whole container. "
        "Exception objects use their standard `repr()` form (for example "
        "`ValueError('bad')`, not a module-qualified type name). `None` is "
        "reported as the two-character string `None`. "
        "Return a JSON object with exactly one key, `observed_state`, whose "
        "value is a JSON array of objects, each with exactly two keys: "
        "`variable` (the variable name as a string) and `value` (the `repr()` "
        "string). Sort the array by `variable` ascending in ASCII order; when "
        "variable names tie, preserve the order in which those variables were "
        "first bound during the invocation."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _load_target_events(args.trace_log)
    observed_state = _observed_state(events)

    oracle_answer = {"observed_state": observed_state}
    payload = {
        "question_kind": "S3_ProgramState",
        "question": _build_question(),
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
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
