#!/usr/bin/env python3
"""Parse trace logs for native_concat head bindings at line 27."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/nativetypes.py"
TARGET_FUNC = "jinja2.nativetypes.native_concat"
CALL_LINE = 16
OBSERVATION_LINE = 27
TRACKED_VARIABLE = "head"

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


def harvest_head_history(trace_log: Path) -> list[str]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    in_invocation = False
    merged: dict[str, str] = {}
    target_events = 0
    line27_count = 0
    history: list[str] = []

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
            line27_count = 0
            continue

        if not in_invocation:
            continue

        if event == "return":
            in_invocation = False
            continue

        if event != "line":
            continue

        merged.update(_parse_locals(parsed["locals"]))

        if lineno == OBSERVATION_LINE:
            line27_count += 1
            if line27_count == 1:
                if TRACKED_VARIABLE not in merged:
                    raise SystemExit(
                        f"Missing {TRACKED_VARIABLE} at first line {OBSERVATION_LINE} "
                        "execution in an invocation"
                    )
                history.append(merged[TRACKED_VARIABLE])

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if len(history) < 8:
        raise SystemExit(
            f"Expected at least 8 head observations, found {len(history)}"
        )

    return history


def build_question() -> str:
    return (
        "Consider the single test method "
        "`jinja_qa/nativetypes_native_concat_s3_state/files/testcase.py::"
        "TestNativeConcatProgramState::test_native_concat_programmatic_rounds`.\n\n"
        "That test calls `jinja2.nativetypes.native_concat` directly in "
        f"`{TARGET_FILE}` (the function beginning at line 16) twenty-five "
        "times with programmatically built inputs.\n\n"
        "An **invocation** means one `call` trace event for "
        f"`{TARGET_FUNC}` recorded at absolute line {CALL_LINE} during the "
        "test run. Count invocations in chronological order starting at 1. "
        "This test performs exactly twenty-five invocations.\n\n"
        "Within one invocation, maintain a map of local variable bindings by "
        f"scanning every `line` event for `{TARGET_FUNC}` from that invocation's "
        f"`call` at line {CALL_LINE} up through the end of that invocation "
        "(the next `return` event for the same function). Each event's "
        "`locals={...}` dictionary supplies bindings that overwrite earlier "
        "bindings for the same name; only keys present in those per-event "
        "dictionaries participate. Do not include bindings from `call` or "
        "`return` events in the merge.\n\n"
        "A **line execution** at absolute line number L means one `line` trace "
        f"event whose file path ends with `{TARGET_FILE}`, whose qualified name "
        f"is `{TARGET_FUNC}`, and whose line number equals L. Count line "
        "executions at a given L within one invocation in chronological order "
        "starting at 1. Multi-line statements use the line where the statement "
        "begins; the `def` line and docstring lines are not executed and never "
        "appear.\n\n"
        f"For each invocation in order (invocation 1 through invocation 25), "
        f"immediately after line {OBSERVATION_LINE} has executed for the first "
        f"time during that invocation, read the binding for `{TRACKED_VARIABLE}` "
        "from the merged map. Collect those binding strings in invocation order "
        "(invocation 1 first, invocation 25 last).\n\n"
        "Each binding string is Python `repr()` output for that local (strings "
        "include their surrounding quote characters, `None` appears as `None`, "
        "booleans as `True`/`False`, and container values are the `repr()` of "
        "the whole container). For example, a list local holding the strings "
        "`'a'` and `'b'` is reported as `['a', 'b']`, and an integer local "
        "holding 9 is reported as `9`.\n\n"
        "Return JSON with top-level key `temporal_value_history`: the flat "
        f"ordered list of `{TRACKED_VARIABLE}` binding strings described above, "
        "one entry per invocation, in chronological invocation order."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    history = harvest_head_history(args.trace_log)
    oracle_answer = {"temporal_value_history": history}
    template_answer = {"temporal_value_history": ["str"]}

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
