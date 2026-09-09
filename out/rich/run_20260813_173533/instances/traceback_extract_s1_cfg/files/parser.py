#!/usr/bin/env python3
"""Parse trace log into S1_IntraProceduralCFG oracle for Traceback.extract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/traceback.py"
TARGET_FUNC = "rich.traceback.Traceback.extract"
INVOCATION_NUMBER = 2

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<abs_file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def _repo_relative_path(abs_file: str) -> str:
    normalized = abs_file.replace("\\", "/")
    marker = f"/{TARGET_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        raise ValueError(
            f"Trace entry file {abs_file!r} does not contain repo-relative "
            f"path {TARGET_FILE!r}"
        )
    return normalized[idx + 1 :]


def _parse_target_events(trace_log: Path) -> list[tuple[str, int]]:
    events: list[tuple[str, int]] = []
    for raw in trace_log.read_text(encoding="utf-8").splitlines():
        match = TRACE_LINE_RE.search(raw)
        if match is None:
            continue
        if TARGET_FILE not in match.group("abs_file").replace("\\", "/"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append((match.group("event"), int(match.group("line"))))
    return events


def _lines_for_invocation(events: list[tuple[str, int]], invocation: int) -> list[int]:
    if invocation < 1:
        raise ValueError(f"Invocation must be >= 1, got {invocation}")

    depth = 0
    invocation_seen = 0
    lines: list[int] = []

    for event, lineno in events:
        if event == "call":
            invocation_seen += 1
            if invocation_seen == invocation:
                depth = 1
                continue
            if depth > 0:
                depth += 1
            continue

        if depth == 0:
            continue

        if event == "return":
            depth -= 1
            if depth == 0:
                break
            continue

        if event == "line":
            lines.append(lineno)
            continue

        if event == "exception":
            raise ValueError(
                "Unexpected exception event inside target function invocation"
            )

    if invocation_seen < invocation:
        raise ValueError(
            f"Trace log contains only {invocation_seen} call event(s) for "
            f"{TARGET_FUNC}, but invocation {invocation} was requested"
        )
    if depth != 0:
        raise ValueError(
            f"Invocation {invocation} of {TARGET_FUNC} has no matching return event"
        )
    if not lines:
        raise ValueError(
            f"Invocation {invocation} of {TARGET_FUNC} produced zero line events"
        )
    return lines


def _build_question() -> str:
    return (
        "Category S1_IntraProceduralCFG (executed_path).\n\n"
        "Run the pytest test "
        "`rich_qa/traceback_extract_s1_cfg/files/testcase.py::"
        "TestTracebackExtractInvocationPath::test_excepthook_drives_extract_paths` "
        "once. Consider only the single test method named above (the class defines "
        "exactly this one test).\n\n"
        "Target function: `rich.traceback.Traceback.extract` (classmethod) in the "
        "repository file `rich/traceback.py`. The test reaches this function "
        "indirectly through Rich's installed `sys.excepthook` handler, which calls "
        "`Traceback.from_exception`, which calls `extract`; do not call `extract` "
        "directly.\n\n"
        "An **invocation** is one `call` tracing event for "
        "`rich.traceback.Traceback.extract` during that test run. Number invocations "
        "starting at 1 in chronological order of those `call` events (nested "
        "recursive `extract` calls inside an outer invocation count as separate "
        "invocations).\n\n"
        f"Report the **executed_path** for invocation **{INVOCATION_NUMBER}** only: "
        "the ordered sequence of `line` tracing events that occur in that invocation, "
        "from the first `line` event after its `call` event through the `line` event "
        "immediately before its matching `return` event. Do not include `call`, "
        "`return`, or `exception` events. Do not include line events from nested "
        "`extract` invocations that start after this invocation's `call` and end before "
        "its `return`.\n\n"
        "Line numbers are 1-based physical line numbers in `rich/traceback.py` as "
        "present in this repository. The `def` line of `extract` and its decorator "
        "lines do not appear because they are not executed as `line` events. For a "
        "multi-line statement, use the line where the statement begins (for example, "
        "if a function call starts on line 50 and its arguments continue on lines "
        "51-52, report line 50 only).\n\n"
        "Output JSON with exactly one top-level key `executed_path` whose value is a "
        "JSON array. Each element is an object with exactly three keys:\n"
        "- `file` (string): always the repo-relative path `rich/traceback.py`\n"
        "- `func` (string): always the dotted qualname "
        "`rich.traceback.Traceback.extract` (module plus class plus method, as in "
        "`rich.traceback.Traceback.extract`)\n"
        "- `line` (integer): the line number described above\n\n"
        "Preserve chronological order; do not sort, deduplicate, or collapse repeated "
        "lines. Include every `line` event in order even when the same line number "
        "appears consecutively or non-consecutively."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_log = Path(args.trace_log)
    if not trace_log.is_file():
        print(f"ERROR: trace log not found: {trace_log}", file=sys.stderr)
        return 1

    if trace_log.stat().st_size == 0:
        print(f"ERROR: trace log is empty: {trace_log}", file=sys.stderr)
        return 1

    events = _parse_target_events(trace_log)
    if not events:
        print(
            f"ERROR: no trace events for {TARGET_FUNC} in {trace_log}",
            file=sys.stderr,
        )
        return 1

    line_numbers = _lines_for_invocation(events, INVOCATION_NUMBER)
    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": lineno}
        for lineno in line_numbers
    ]

    oracle_answer = {"executed_path": executed_path}
    template_answer = {
        "executed_path": [{"file": "str", "func": "str", "line": "int"}]
    }

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": _build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(executed_path)} executed_path entries to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
