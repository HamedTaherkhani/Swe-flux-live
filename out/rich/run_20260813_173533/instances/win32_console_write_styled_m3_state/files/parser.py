#!/usr/bin/env python3
"""Parse trace log into M3_ProgramState oracle for LegacyWindowsTerm.write_styled."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/_win32_console.py"
TARGET_FUNC = "rich._win32_console.LegacyWindowsTerm.write_styled"
OBSERVATION_LINE = 438

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)


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


def _parse_int(local_repr: str, name: str) -> int:
    try:
        value = ast.literal_eval(local_repr)
    except (SyntaxError, ValueError) as exc:
        raise SystemExit(f"Unable to parse local {name}={local_repr!r}") from exc
    if not isinstance(value, int):
        raise SystemExit(f"Local {name} is not an int: {local_repr!r}")
    return value


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
        events.append(
            {
                "lineno": int(match.group("lineno")),
                "event": match.group("event"),
                "locals": _parse_locals(match.group("locals")),
            }
        )

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )
    return events


def _composite_state(fore: int, back: int) -> str:
    return repr(fore | (back << 4))


def _compute_unique_values(events: list[dict]) -> list[str]:
    in_invocation = False
    bindings: dict[str, str] = {}
    seen: set[str] = set()

    for event in events:
        event_type = event["event"]
        if event_type == "call":
            in_invocation = True
            bindings = {}
            continue
        if event_type == "return":
            in_invocation = False
            bindings = {}
            continue
        if not in_invocation or event_type != "line":
            continue

        bindings.update(event["locals"])
        if event["lineno"] != OBSERVATION_LINE:
            continue
        if "fore" not in bindings or "back" not in bindings:
            raise SystemExit(
                f"Missing fore/back at line {OBSERVATION_LINE} after binding "
                f"accumulation: {bindings}"
            )
        fore = _parse_int(bindings["fore"], "fore")
        back = _parse_int(bindings["back"], "back")
        seen.add(_composite_state(fore, back))

    if not seen:
        raise SystemExit(
            f"No observations at line {OBSERVATION_LINE} for {TARGET_FUNC}"
        )
    return sorted(seen)


QUESTION = """\
During pytest run of all test methods in \
rich_qa/win32_console_write_styled_m3_state/files/testcase.py::TestLegacyWindowsWriteStyledState \
(the class defines twelve test methods; pytest collects them in definition order: \
test_named_palette_batch, test_rgb_gradient_batch, test_edge_mode_batch, \
test_bold_only_sweep, test_dim_bright_sweep, test_reverse_sweep, \
test_background_only_sweep, test_foreground_only_sweep, test_mixed_attribute_batch, \
test_default_and_bold_dim, test_ansi_number_sweep, test_combined_seed_batches), \
consider every invocation of \
rich._win32_console.LegacyWindowsTerm.write_styled in rich/_win32_console.py \
(source lines 405-442).

An invocation is one call event for write_styled during the full pytest session, \
counted in chronological order across all twelve test methods (1-based).

At each invocation, observe the program state immediately before the first \
SetConsoleTextAttribute call on source line 438 executes—that is, on the line \
event for line 438 inside that invocation. Read locals fore and back from the \
function frame's accumulated local bindings at that moment (values assigned on \
earlier lines in the same invocation remain in scope even if the line-438 event \
records no changed locals). Line numbers are \
1-based positions in rich/_win32_console.py as checked into the repository; only \
the line where a statement begins is numbered.

From fore and back at that observation point, form the combined Windows console \
attribute integer fore | (back << 4) (bitwise OR of foreground attribute fore \
with background attribute back shifted left by four). Report each distinct value \
as a Python repr() string of that integer (for example the integer 64 is reported \
as the two-character string '64', not as a JSON number).

Collect the sorted set of distinct such repr strings across all invocations of \
write_styled in that pytest run. Sort ascending by Python string comparison on \
the repr strings themselves (lexicographic order). Remove duplicates.

Report the answer using the unique_values shape: a JSON object with key \
unique_values whose value is a list of strings.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 60:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 60"
        )
    distinct_lines = {event["lineno"] for event in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )
    line_counts: dict[int, int] = {}
    for event in line_events:
        line_counts[event["lineno"]] = line_counts.get(event["lineno"], 0) + 1
    if max(line_counts.values()) < 5:
        raise SystemExit("No line executed at least 5 times")

    unique_values = _compute_unique_values(events)
    if len(unique_values) < 8:
        raise SystemExit(
            f"Insufficient unique values: {len(unique_values)} < 8"
        )

    oracle_answer = {"unique_values": unique_values}
    template_answer = {"unique_values": ["str"]}

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
