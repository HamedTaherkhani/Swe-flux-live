#!/usr/bin/env python3
"""Parse trace logs for ext_parse_s2_loops (S2_Loops iteration count)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/ext.py"
TARGET_FUNC = "jinja2.ext.InternationalizationExtension.parse"
LOOP_HEADER_LINE = 353
LOOP_BODY_FIRST_LINE = 354
TARGET_INVOCATION = 1

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
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


def _parse_trace_line(raw_line: str) -> dict[str, str | int] | None:
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
    }


def _load_target_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
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


def _count_loop_iterations(events: list[dict[str, str | int]]) -> int:
    invocation = 0
    in_target = False
    iteration_count = 0

    for event in events:
        kind = str(event["event"])
        lineno = int(event["lineno"])

        if kind == "call":
            invocation += 1
            in_target = invocation == TARGET_INVOCATION
            if in_target:
                iteration_count = 0
            continue

        if not in_target:
            continue

        if kind == "return" or kind == "exception":
            in_target = False
            continue

        if kind == "line" and lineno == LOOP_BODY_FIRST_LINE:
            iteration_count += 1

    if invocation < TARGET_INVOCATION:
        _fail(
            f"trace contains only {invocation} invocation(s) of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if iteration_count == 0:
        _fail(
            f"no line events at {TARGET_FILE}:{LOOP_BODY_FIRST_LINE} during "
            f"invocation {TARGET_INVOCATION}"
        )

    return iteration_count


def _build_question() -> str:
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/ext_parse_s2_loops/files/testcase.py::ExtParseS2LoopsTest::"
        "test_extract_translations_drives_trans_header_loop` (test class "
        "`ExtParseS2LoopsTest`, test method "
        "`test_extract_translations_drives_trans_header_loop`). "
        "During that single test run, the function "
        "`jinja2.ext.InternationalizationExtension.parse` in `src/jinja2/ext.py` "
        "is executed. An invocation is one `call` of that function during the "
        "test run, counted in chronological order starting at 1. "
        f"For invocation {TARGET_INVOCATION} only, consider the `while` loop whose "
        f"header begins on line {LOOP_HEADER_LINE} of `src/jinja2/ext.py` "
        "(the loop `while parser.stream.current.type != \"block_end\":`). "
        f"Define iteration counting as 1-based: iteration N is the Nth time line "
        f"{LOOP_BODY_FIRST_LINE} (`if variables:`), the loop body's first line, "
        "executes during that invocation. Count an iteration whether the loop "
        "body later `continue`s, `break`s, or falls through to the next "
        "iteration. Line numbers are absolute, 1-based, and refer to "
        "`src/jinja2/ext.py` as it exists in the repository; for multi-line "
        "statements, attribute executed-line events to the line where that "
        "statement begins. "
        "How many iterations did that loop perform during invocation "
        f"{TARGET_INVOCATION}? "
        "Report the answer as a JSON object with exactly one key, "
        "`loop_iteration_count`, whose value is a JSON number (bare integer, "
        "not a quoted string)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _load_target_events(args.trace_log)
    loop_iteration_count = _count_loop_iterations(events)

    oracle_answer = {"loop_iteration_count": loop_iteration_count}
    payload = {
        "question_kind": "S2_Loops",
        "question": _build_question(),
        "template_answer": {"loop_iteration_count": "int"},
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
