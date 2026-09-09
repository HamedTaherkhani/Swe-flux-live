#!/usr/bin/env python3
"""Parse trace log into oracle.json for async_utils_decorator_m3_state."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/async_utils.py"
TARGET_FUNC = "jinja2.async_utils.async_variant.<locals>.decorator"
CALL_LINE = 16
RETURN_LINE = 54

QUESTION = """\
During the pytest run for test class \
`jinja_qa/async_utils_decorator_m3_state/files/testcase.py::TestAsyncVariantDecoratorDirect`, \
aggregate observations across **all** `test_*` methods in that class. Methods are \
identified by their pytest node ids and are ordered chronologically as pytest executes \
them (unittest discovery order: ascending ASCII by method name).

The target function is `jinja2.async_utils.async_variant.<locals>.decorator` defined in \
`src/jinja2/async_utils.py` (the nested `def decorator` inside `async_variant` begins at \
line 16 in that file as checked into this repository). Each test method calls this \
function directly via `async_variant(sync_func)(async_func)` (possibly after applying \
`pass_environment`, `pass_eval_context`, or `pass_context` to the sync function).

Track the local parameter `async_func` (the async callable passed into `decorator`). \
At each observation point below, read its runtime `__name__` attribute and record \
Python `repr(async_func.__name__)` — the quoted string form `repr` produces for the bare \
name (for example a function whose `__name__` is `greet` is reported as `'greet'`, \
including the surrounding single-quote characters).

Observation points (every matching trace event during the run counts):

1. Each `call` event at **line 16** in `src/jinja2/async_utils.py` for the target \
function, when the logged locals mapping contains an `async_func` key.
2. Each `return` event at **line 54** in `src/jinja2/async_utils.py` for the target \
function, when the logged locals mapping contains an `async_func` key.

Line numbers are absolute, 1-based, and refer to the file as it exists in the repository. \
For a multi-line statement, the executed-line event is attributed to the line where that \
statement begins. The `def decorator` line (line 16) can emit a `call` event; docstring \
lines inside `decorator` are not present in this function.

An **invocation** is one entry into `decorator` (one `call` event for this function) during \
the pytest run, numbered 1-based in chronological order. Only events whose qualified \
function name is exactly `jinja2.async_utils.async_variant.<locals>.decorator` and whose \
file path ends with `src/jinja2/async_utils.py` count. Events from import-time module \
initialization are outside the pytest test window and must be ignored.

If `async_func` is absent from the logged locals mapping at an observation point, skip \
that point.

Collect the set of distinct repr strings observed across all invocations and all \
observation points in the run. Sort the final list in ascending ASCII order (bytewise / \
`strcmp` order, no locale collation). Do not deduplicate beyond set membership: each \
distinct repr appears exactly once.

Return JSON with top-level key `unique_values` whose value is that sorted list of Python \
`repr` strings.\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)
ASYNC_FUNC_RE = re.compile(r"'async_func': '<function (.+?) at 0x[0-9a-fA-F]+>'")


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _extract_async_func_name(locals_str: str) -> str | None:
    match = ASYNC_FUNC_RE.search(locals_str)
    if match is None:
        return None
    return match.group(1)


def _parse_trace_events(
    trace_log: Path,
) -> list[tuple[str, str, int, str, str | None]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[str, str, int, str, str | None]] = []
    for raw_line in text.splitlines():
        if TARGET_FUNC not in raw_line:
            continue
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        rel_file = _repo_relative_path(match.group("file"))
        if rel_file != TARGET_REL_FILE:
            continue
        locals_idx = raw_line.find(" locals=")
        locals_str = raw_line[locals_idx + len(" locals=") :] if locals_idx != -1 else None
        events.append(
            (
                rel_file,
                match.group("func"),
                int(match.group("line")),
                match.group("event"),
                locals_str,
            )
        )

    if not events:
        raise SystemExit(
            f"ERROR: no trace events for {TARGET_FUNC} in {trace_log}"
        )

    return events


def _is_observation_point(line: int, event: str) -> bool:
    if event == "call" and line == CALL_LINE:
        return True
    if event == "return" and line == RETURN_LINE:
        return True
    return False


def _unique_async_func_names(
    events: list[tuple[str, str, int, str, str | None]],
) -> list[str]:
    observed: set[str] = set()
    for _file, _func, line, event, locals_str in events:
        if not _is_observation_point(line, event):
            continue
        if locals_str is None:
            continue
        name = _extract_async_func_name(locals_str)
        if name is None:
            continue
        observed.add(repr(name))

    if len(observed) < 8:
        raise SystemExit(
            f"ERROR: expected at least 8 distinct async_func names, found {len(observed)}"
        )

    return sorted(observed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_counts: dict[int, int] = {}
    distinct_lines: set[int] = set()
    for _f, _fn, line, event, _loc in events:
        if event == "line":
            distinct_lines.add(line)
            line_counts[line] = line_counts.get(line, 0) + 1

    if len([event for event in events if event[3] == "line"]) < 60:
        raise SystemExit("ERROR: expected at least 60 line events for target function")
    if len(distinct_lines) < 8:
        raise SystemExit("ERROR: expected at least 8 distinct executed lines")
    if not any(count >= 5 for count in line_counts.values()):
        raise SystemExit("ERROR: expected at least one line executed 5+ times")

    unique_values = _unique_async_func_names(events)
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


if __name__ == "__main__":
    main()
