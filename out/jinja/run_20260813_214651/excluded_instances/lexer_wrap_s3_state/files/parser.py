#!/usr/bin/env python3
"""Parse a line trace of Lexer.wrap and emit the S3_ProgramState oracle."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/lexer.py"
TARGET_FUNC = "jinja2.lexer.Lexer.wrap"
CALL_LINE = 615
RETURN_LINE = 624
OBSERVATION_LINE = 667
OBSERVATION_K = 77
REQUESTED_VARIABLES = ("lineno", "token", "value", "value_str")

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?(?:\s+exc=(?P<exc>.*?))?\s+locals=(?P<locals>\{.*\})$"
)


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Could not parse locals dict: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected locals dict, got {type(parsed)!r}")
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    groups = match.groupdict()
    return {
        "path": groups["path"].replace("\\", "/"),
        "lineno": groups["lineno"],
        "func": groups["func"],
        "event": groups["event"],
        "locals": groups["locals"] or "{}",
    }


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def harvest_observed_state(trace_log: Path) -> dict[str, str]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    in_invocation = False
    target_events = 0
    merged: dict[str, str] = {}
    execution_count = 0
    observed: dict[str, str] | None = None

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]
        lineno = int(parsed["lineno"])

        if event == "call" and lineno == CALL_LINE:
            in_invocation = True
            merged = {}
            execution_count = 0
            observed = None
            continue

        if not in_invocation:
            continue

        if event == "return" and lineno == RETURN_LINE:
            break

        if event != "line":
            continue

        merged.update(_parse_locals(parsed["locals"]))

        if lineno == OBSERVATION_LINE:
            execution_count += 1
            if execution_count == OBSERVATION_K:
                observed = {
                    name: merged[name]
                    for name in REQUESTED_VARIABLES
                    if name in merged
                }

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if observed is None:
        raise SystemExit(
            f"Observation point line {OBSERVATION_LINE} execution {OBSERVATION_K} "
            "was not reached in the traced invocation"
        )

    missing = [name for name in REQUESTED_VARIABLES if name not in observed]
    if missing:
        raise SystemExit(
            f"Missing requested variables at observation point: {missing}"
        )

    return observed


def build_question() -> str:
    variables = ", ".join(f"`{name}`" for name in REQUESTED_VARIABLES)
    return (
        "Consider the single test method "
        "`jinja_qa/lexer_wrap_s3_state/files/testcase.py::"
        "TestLexerWrapProgramState::test_compile_programmatic_template`.\n\n"
        "That test compiles a programmatic Jinja template by calling "
        "`Environment.from_string`, which eventually invokes "
        "`jinja2.lexer.Lexer.wrap` in `src/jinja2/lexer.py` (the `wrap` method "
        "starting at line 615).\n\n"
        "An **invocation** of `Lexer.wrap` means one `call` trace event recorded "
        f"at absolute line {CALL_LINE} of `src/jinja2/lexer.py` inside "
        f"`{TARGET_FUNC}` during the test run. Count invocations in "
        "chronological order starting at 1. This test triggers exactly one "
        "such invocation.\n\n"
        "Within that invocation, a **line execution** at absolute line number L "
        "means one `line` trace event whose file path ends with "
        f"`{TARGET_FILE}` and whose line number equals L inside `{TARGET_FUNC}`. "
        "Count line executions at a given L in chronological order starting at 1. "
        "Multi-line statements use the line where the statement begins.\n\n"
        "To determine local variable bindings at an observation point, scan every "
        f"`line` event for `{TARGET_FUNC}` in chronological order from the "
        f"invocation's `call` at line {CALL_LINE} up to and including the "
        f"{OBSERVATION_K}-th line execution at line {OBSERVATION_LINE}. Maintain a "
        "map of variable names to value strings; each event's `locals={...}` "
        "dictionary (keys sorted in the trace output) supplies bindings that "
        "overwrite any earlier binding for the same name. Only keys present in "
        "those per-event dictionaries participate; variables never mentioned are "
        "absent.\n\n"
        f"Immediately after line {OBSERVATION_LINE} has executed for the "
        f"{OBSERVATION_K}-th time during that invocation, report the bindings for "
        f"{variables}.\n\n"
        "Each reported value is the exact string stored in the merged map (the "
        "trace logger records each local using Python `repr()`, so strings include "
        "their surrounding quotes, `None` appears as `None`, booleans as `True`/`False`, "
        "and container values are the `repr()` of the whole container). For example, "
        "a string local holding `hello` is reported as `'hello'`, and an integer "
        "local holding 3 is reported as `3`.\n\n"
        "Return JSON with top-level key `observed_state`: a list of objects, each "
        "with keys `variable` (the variable name) and `value` (its merged binding "
        "string). Sort the list by `variable` ascending (Unicode code-point order); "
        "break ties by `value` ascending."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    observed = harvest_observed_state(args.trace_log)
    oracle_answer = {
        "observed_state": [
            {"variable": name, "value": observed[name]}
            for name in sorted(observed)
        ]
    }
    template_answer = {
        "observed_state": [{"variable": "str", "value": "str"}]
    }

    payload = {
        "question_kind": "S3_ProgramState",
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
