#!/usr/bin/env python3
"""Parse trace log into oracle.json for parser_parse_test_m3_state."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/parser.py"
TARGET_FUNC = "jinja2.parser.Parser.parse_test"
OBSERVATION_LINES = {960, 988}

QUESTION = """\
During the pytest run for test class \
`jinja_qa/parser_parse_test_m3_state/files/testcase.py::TestParserParseTestIndirect`, \
aggregate observations across **all** `test_*` methods in that class. Methods are \
identified by their pytest node ids and are ordered chronologically as pytest executes \
them (unittest discovery order: ascending ASCII by method name).

The target function is `jinja2.parser.Parser.parse_test` defined in `src/jinja2/parser.py` \
(the `def parse_test` line is line 952 in that file as checked into this repository). \
Each time this function runs while parsing Jinja template source via `Environment.parse`, \
it is reached indirectly through the parser call chain (for example \
`Parser.parse_unary` → `Parser.parse_filter_expr` → `Parser.parse_test`); you must \
not assume any test calls it directly.

Track the local variable `name` (the test-name string assembled inside `parse_test`). \
Record its value at these **observation points** within every invocation of \
`jinja2.parser.Parser.parse_test` during the run:

1. Each `line` event at **line 960** in `src/jinja2/parser.py` where the logged locals \
mapping contains a `name` key. Line 960 is `while self.stream.current.type == "dot":`; \
after the initial binding on line 959 and after each suffix segment is appended in the loop \
body, the updated `name` is visible on the next execution of line 960.
2. Each `return` event at **line 988** in `src/jinja2/parser.py` where the logged locals \
mapping contains a `name` key. Line 988 is the `return node` statement.

Line numbers are absolute, 1-based, and refer to the file as it exists in the repository. \
For a multi-line statement, the executed-line event is attributed to the line where that \
statement begins.

An **invocation** is one entry into `parse_test` (one `call` event for this function) during \
the pytest run, numbered 1-based in chronological order. Only events whose qualified \
function name is exactly `jinja2.parser.Parser.parse_test` and whose file path ends with \
`src/jinja2/parser.py` count.

At each observation point above, take the value of `name` as Python `repr(name)` — the same \
serialization `repr` would produce for the runtime `str` object (for example the test name \
whose characters are d-e-f-i-n-e-d is reported as the six-character string `'defined'`, \
including its surrounding quote characters in the repr). If `name` is absent from the logged \
locals mapping at an observation point, skip that point.

Collect the set of distinct repr strings observed across all invocations and all observation \
points in the run. Sort the final list in ascending ASCII order (bytewise / `strcmp` order, \
no locale collation). Do not deduplicate beyond set membership: each distinct repr appears \
exactly once.

Return JSON with top-level key `unique_values` whose value is that sorted list of Python \
`repr` strings.\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _parse_one_literal(fragment: str) -> tuple[object, int]:
    fragment = fragment.lstrip()
    for end in range(1, len(fragment) + 1):
        candidate = fragment[:end]
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue
        return value, end
    raise ValueError(f"unable to parse literal from {fragment[:80]!r}")


def _extract_local_value(locals_str: str, key: str) -> str | None:
    marker = f"'{key}': "
    start = locals_str.find(marker)
    if start == -1:
        return None
    tail = locals_str[start + len(marker) :]
    try:
        value, _consumed = _parse_one_literal(tail)
    except ValueError:
        return None
    if not isinstance(value, str):
        return None
    return value


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
    if line not in OBSERVATION_LINES:
        return False
    if line == 960:
        return event == "line"
    if line == 988:
        return event == "return"
    return False


def _unique_name_values(
    events: list[tuple[str, str, int, str, str | None]],
) -> list[str]:
    observed: set[str] = set()
    for _file, _func, line, event, locals_str in events:
        if not _is_observation_point(line, event):
            continue
        if locals_str is None:
            continue
        name_value = _extract_local_value(locals_str, "name")
        if name_value is None:
            continue
        observed.add(name_value)

    if len(observed) < 8:
        raise SystemExit(
            f"ERROR: expected at least 8 distinct name values, found {len(observed)}"
        )

    return sorted(observed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_events = [
        event for event in events if event[3] == "line" and event[2] in OBSERVATION_LINES
    ]
    distinct_lines = {line for _f, _fn, line, event, _loc in events if event == "line"}
    line_counts: dict[int, int] = {}
    for _f, _fn, line, event, _loc in events:
        if event == "line":
            line_counts[line] = line_counts.get(line, 0) + 1

    if len([event for event in events if event[3] == "line"]) < 60:
        raise SystemExit("ERROR: expected at least 60 line events for target function")
    if len(distinct_lines) < 8:
        raise SystemExit("ERROR: expected at least 8 distinct executed lines")
    if not any(count >= 5 for count in line_counts.values()):
        raise SystemExit("ERROR: expected at least one line executed 5+ times")

    unique_values = _unique_name_values(events)
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
