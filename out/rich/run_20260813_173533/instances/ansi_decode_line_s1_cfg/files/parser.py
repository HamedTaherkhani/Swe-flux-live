#!/usr/bin/env python3
"""Parse a trace log into an S1_IntraProceduralCFG oracle for decode_line."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "S1_IntraProceduralCFG"
TARGET_FILE = "rich/ansi.py"
TARGET_FUNC = "rich.ansi.AnsiDecoder.decode_line"
TARGET_INVOCATION = 11

QUESTION = """\
During pytest run rich_qa/ansi_decode_line_s1_cfg/files/testcase.py::AnsiDecodeLineCfgTest::test_seeded_multiline_ansi_decode, consider the function rich.ansi.AnsiDecoder.decode_line defined in rich/ansi.py (the def statement is on line 138).

An invocation of decode_line is one call event for that function during the entire test run. Number invocations starting at 1 in chronological order of their call events (earliest call is invocation 1).

Using sys.settrace (or equivalent) with line events enabled for every executed source line in decode_line, record the ordered sequence of line events that occur strictly after the call event begins and strictly before the matching return event ends for invocation 11 only.

Include only event=line records for frames whose func equals rich.ansi.AnsiDecoder.decode_line (the module-qualified name format: package.module.Class.method, e.g. rich.color.Color.from_ansi). Do not include call, return, or exception events. Do not include line events from any other function, including _ansi_tokenize or callees invoked from decode_line.

The def line (line 138), decorator lines, and docstring lines must not appear in the sequence—only executable body lines reached during the invocation. For a multi-line statement, Python reports the line event on the line where that statement begins; for example, a call split across lines 186–191 is reported as line 186 when execution enters that statement, not on continuation lines. decode_line contains several such multi-line Style.from_color and from_rgb calls in the SGR color branches.

Report the answer as JSON with top-level key executed_path whose value is a list of objects in execution order with no deduplication (repeat the same line number whenever a separate line event fires). Each object has exactly these keys:
- file (str): repo-relative path, always rich/ansi.py for this question
- func (str): always rich.ansi.AnsiDecoder.decode_line
- line (int): 1-based physical line number in rich/ansi.py as present in the repository

Preserve the exact chronological order produced by tracing; do not sort or reorder events.\
"""

TEMPLATE_ANSWER = {
    "executed_path": [
        {"file": "str", "func": "str", "line": "int"},
    ],
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = TARGET_FILE
    idx = normalized.rfind(marker)
    if idx == -1:
        raise ValueError(f"trace path does not contain {marker!r}: {path!r}")
    return normalized[idx:]


def _parse_invocation_line_events(trace_log: Path) -> list[list[int]]:
    if not trace_log.is_file():
        raise SystemExit(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_log}")

    invocations: list[list[int]] = []
    current_lines: list[int] | None = None
    matched_events = 0

    for raw_line in text.splitlines():
        match = TRACE_LINE_RE.match(raw_line)
        if not match:
            continue

        file_path = _normalize_file(match.group("file"))
        if file_path != TARGET_FILE:
            continue

        func_name = match.group("func")
        if func_name != TARGET_FUNC:
            continue

        matched_events += 1
        event = match.group("event")
        line_no = int(match.group("line"))

        if event == "call":
            current_lines = []
            invocations.append(current_lines)
        elif event == "line" and current_lines is not None:
            current_lines.append(line_no)
        elif event == "return":
            current_lines = None

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if len(invocations) < TARGET_INVOCATION:
        raise SystemExit(
            f"expected at least {TARGET_INVOCATION} invocations, found {len(invocations)}"
        )

    return invocations


def _build_answer(line_numbers: list[int]) -> dict:
    if not line_numbers:
        raise SystemExit("invocation has zero line events")

    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line_no}
        for line_no in line_numbers
    ]
    return {"executed_path": executed_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    invocations = _parse_invocation_line_events(args.trace_log)
    line_events = invocations[TARGET_INVOCATION - 1]
    oracle_answer = _build_answer(line_events)

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
