#!/usr/bin/env python3
"""Parse trace logs for generate_identifier_pattern_main_s6_calls (S6_InterProceduralCFG)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "scripts/generate_identifier_pattern.py"
TARGET_FUNC = "scripts.generate_identifier_pattern.main"
TARGET_INVOCATION = 7

TRACKED_FUNCS: tuple[str, ...] = (
    "scripts.generate_identifier_pattern.build_pattern",
    "scripts.generate_identifier_pattern.collapse_ranges",
    "scripts.generate_identifier_pattern.get_characters",
    "scripts.generate_identifier_pattern.main",
)
TRACKED_SET = set(TRACKED_FUNCS)

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


def _load_trace_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is not None:
            events.append(parsed)

    if not events:
        _fail(f"trace log contains no parseable events: {trace_log}")
    return events


def _count_target_activity(events: list[dict[str, str | int]]) -> tuple[int, int, int, set[str]]:
    line_events = 0
    distinct_lines: set[int] = set()
    call_events = 0
    traced_funcs_called: set[str] = set()

    for event in events:
        if event["file"] != TARGET_FILE or event["func"] != TARGET_FUNC:
            continue
        if event["event"] == "line":
            line_events += 1
            distinct_lines.add(int(event["lineno"]))
        elif event["event"] == "call":
            call_events += 1

    for event in events:
        if event["file"] != TARGET_FILE:
            continue
        if event["event"] == "call" and event["func"] in TRACKED_SET:
            traced_funcs_called.add(str(event["func"]))

    return line_events, len(distinct_lines), call_events, traced_funcs_called


def _compute_function_call_order(
    events: list[dict[str, str | int]],
    invocation: int,
) -> list[dict[str, str]]:
    invocation_counter = 0
    recording = False
    sequence: list[dict[str, str]] = []

    for event in events:
        func = str(event["func"])
        kind = str(event["event"])

        if kind == "call" and func == TARGET_FUNC:
            invocation_counter += 1
            if invocation_counter == invocation:
                recording = True
            continue

        if recording and kind == "call" and func in TRACKED_SET:
            sequence.append({"file": TARGET_FILE, "func": func})

        if kind == "return" and func == TARGET_FUNC and recording:
            recording = False

    if invocation_counter < invocation:
        _fail(
            f"only {invocation_counter} invocations of {TARGET_FUNC}; "
            f"requested invocation {invocation}"
        )
    if not sequence:
        _fail(
            f"no tracked function calls recorded during invocation "
            f"{invocation} of {TARGET_FUNC}"
        )
    return sequence


def _build_question() -> str:
    tracked_list = ", ".join(
        f"`{name}`"
        for name in TRACKED_FUNCS
        if name != TARGET_FUNC
    )
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/generate_identifier_pattern_main_s6_calls/files/testcase.py::"
        "GenerateIdentifierPatternMainS6CallsTest::test_main_seeded_unicode_scan_batches` "
        "(test class `GenerateIdentifierPatternMainS6CallsTest`, test method "
        "`test_main_seeded_unicode_scan_batches`). "
        "During that single test run, the function "
        f"`{TARGET_FUNC}` in `{TARGET_FILE}` is invoked multiple times. "
        "Function identity in this answer uses the dotted qualname format "
        "`module.function` (for example "
        "`scripts.generate_identifier_pattern.build_pattern`). "
        "An invocation of `main` is one `call` event to that function during "
        "the test run; number invocations chronologically starting at 1 for "
        "the first `call`, 2 for the next, and so on. "
        f"Answer for the **{TARGET_INVOCATION}th invocation** only. "
        "Track calls to exactly these functions in `{TARGET_FILE}`: "
        f"{tracked_list}. "
        "Do not include `call` events for `main` itself in the answer sequence. "
        "The inclusion rule: include every `call` event for a tracked function "
        "that occurs chronologically between the `call` event that starts the "
        f"{TARGET_INVOCATION}th invocation of `main` and the matching `return` "
        "event that ends that same invocation. This includes calls made "
        "directly from `main` and calls made by tracked callees nested inside "
        "those calls (for example `get_characters` resumed while "
        "`collapse_ranges` consumes its generator, or `collapse_ranges` "
        "resumed while `build_pattern` iterates its result). Do not include "
        "calls to functions outside the tracked set above (for example the "
        "inner `lambda` in `collapse_ranges`, builtins, or stdlib helpers). "
        "In CPython, each time a generator frame is entered—including the "
        "initial call and every resumption after `yield`—the tracer emits a "
        "`call` event for that generator function; treat each such `call` "
        "event as a separate entry in the sequence. Include every matching "
        "call separately; do not deduplicate repeated calls to the same "
        "function. "
        "Order the sequence by chronological `call` event order during that "
        "invocation. "
        "Report the answer as a JSON object with exactly one key, "
        "`function_call_order`, whose value is a JSON array of objects each "
        "having keys `file` (repo-relative path string, e.g. "
        f"`{TARGET_FILE}`) and `func` (dotted qualname string)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _load_trace_events(args.trace_log)

    target_line_events, distinct_lines, target_calls, traced_funcs_called = (
        _count_target_activity(events)
    )
    if target_line_events < 40:
        _fail(
            f"only {target_line_events} line events for {TARGET_FUNC}; "
            "need at least 40"
        )
    if distinct_lines < 8:
        _fail(
            f"only {distinct_lines} distinct executed lines for {TARGET_FUNC}; "
            "need at least 8"
        )
    if target_calls < 10:
        _fail(
            f"only {target_calls} call events for {TARGET_FUNC}; need at least 10"
        )
    if len(traced_funcs_called) < 2:
        _fail(
            f"only {len(traced_funcs_called)} distinct tracked functions called; "
            "need at least 2"
        )

    call_order = _compute_function_call_order(events, TARGET_INVOCATION)
    oracle_answer = {"function_call_order": call_order}
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": _build_question(),
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
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
