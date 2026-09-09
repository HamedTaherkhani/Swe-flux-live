#!/usr/bin/env python3
"""Parse trace log into oracle.json for bccache_dump_bytecode_s5_exceptions."""

from __future__ import annotations

import argparse
import builtins
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/bccache.py"
TARGET_FUNC = "jinja2.bccache.FileSystemBytecodeCache.dump_bytecode"

QUESTION = """\
During the pytest run identified by the test id \
`jinja_qa/bccache_dump_bytecode_s5_exceptions/files/testcase.py::TestFileSystemBytecodeCacheDumpBytecode::test_dump_bytecode_caught_exception_paths`, \
consider every trace event for the function `jinja2.bccache.FileSystemBytecodeCache.dump_bytecode` \
defined in `src/jinja2/bccache.py` (the `def dump_bytecode` line is line 275 in that file).

An **invocation** is one `call` event for this function during the pytest run. Number invocations \
1-based in chronological order. For each invocation, the invocation span runs from its `call` \
event up to but not including the next `call` event for this function, or through the end of \
the trace if no later `call` exists.

An exception is **caught inside** `jinja2.bccache.FileSystemBytecodeCache.dump_bytecode` when, \
within a single invocation span, a trace `exception` event for this function is followed by at \
least one subsequent `line` event for this function before that invocation's `return` event. \
Exceptions whose `exception` event is not followed by any `line` event in the same invocation \
before its `return` are propagated out and must not be counted.

Collect the set of exception types for all caught exceptions across every invocation during this \
test run. Each type is reported using this naming convention: if the exception class's defining \
module is `builtins`, report bare `type(exc).__name__` (for example `ValueError`, never \
`builtins.ValueError`); otherwise report `{exc.__class__.__module__}.{exc.__class__.__qualname__}` \
(for example `haystack.core.errors.PipelineError`). Derive the type from the `exc=` field on each \
qualifying `exception` event, which has the form `ShortName: ...` where `ShortName` is \
`type(exc).__name__`.

Sort the reported type strings in ascending ASCII order. Remove duplicates: each distinct type \
appears at most once.

Return JSON with top-level key `caught_exception_kinds` whose value is the sorted list of type \
strings described above.\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>[^\s]+(?:\s[^\s=][^\n]*)?))?"
)


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _parse_trace_events(trace_log: Path) -> list[tuple[str, str, int, str, str | None]]:
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
        events.append(
            (
                rel_file,
                match.group("func"),
                int(match.group("line")),
                match.group("event"),
                match.group("exc"),
            )
        )

    if not events:
        raise SystemExit(
            f"ERROR: no trace events for {TARGET_FUNC} in {trace_log}"
        )

    return events


def _invocation_spans(
    events: list[tuple[str, str, int, str, str | None]],
) -> list[tuple[int, int]]:
    call_indices = [
        index for index, (_f, _fn, _ln, event, _exc) in enumerate(events) if event == "call"
    ]
    if not call_indices:
        raise SystemExit("ERROR: no call events for target function")

    spans: list[tuple[int, int]] = []
    for position, start in enumerate(call_indices):
        end = call_indices[position + 1] if position + 1 < len(call_indices) else len(events)
        spans.append((start, end))
    return spans


def _exception_short_name(exc_field: str | None) -> str:
    if not exc_field:
        raise SystemExit("ERROR: exception event missing exc= field")
    short_name, separator, _rest = exc_field.partition(":")
    if not separator:
        raise SystemExit(f"ERROR: malformed exc field: {exc_field!r}")
    return short_name.strip()


def _format_exception_type(short_name: str) -> str:
    builtin_obj = getattr(builtins, short_name, None)
    if (
        isinstance(builtin_obj, type)
        and issubclass(builtin_obj, BaseException)
        and builtin_obj.__module__ == "builtins"
    ):
        return short_name

    raise SystemExit(f"ERROR: unable to resolve exception type {short_name!r}")


def _is_caught_in_span(
    events: list[tuple[str, str, int, str, str | None]], index: int, span_end: int
) -> bool:
    for later in range(index + 1, span_end):
        _file, _func, _line, event, _exc = events[later]
        if event == "return":
            return False
        if event == "line":
            return True
    return False


def _caught_exception_kinds(
    events: list[tuple[str, str, int, str, str | None]],
) -> list[str]:
    kinds: set[str] = set()
    for start, end in _invocation_spans(events):
        for index in range(start, end):
            _file, _func, _line, event, exc_field = events[index]
            if event != "exception":
                continue
            if not _is_caught_in_span(events, index, end):
                continue
            short_name = _exception_short_name(exc_field)
            kinds.add(_format_exception_type(short_name))

    if not kinds:
        raise SystemExit("ERROR: no caught exception kinds found in trace")

    return sorted(kinds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    line_events = [event for event in events if event[3] == "line"]
    distinct_lines = {line for _f, _fn, line, _event, _exc in line_events}
    exception_events = [event for event in events if event[3] == "exception"]

    if len(line_events) < 30:
        raise SystemExit(
            f"ERROR: expected at least 30 line events, found {len(line_events)}"
        )
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"ERROR: expected at least 8 distinct executed lines, found {len(distinct_lines)}"
        )
    if len(exception_events) < 1:
        raise SystemExit("ERROR: expected at least 1 exception event")

    caught_kinds = _caught_exception_kinds(events)
    oracle_answer = {"caught_exception_kinds": caught_kinds}
    template_answer = {"caught_exception_kinds": ["str"]}

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
