#!/usr/bin/env python3
"""Parse trace log into oracle.json for async_utils_wrapper_s6_calls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/async_utils.py"
TARGET_FUNC = "jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper"
WRAPPER_CALL_LINE = 37
IS_ASYNC_FUNC = "jinja2.async_utils.async_variant.<locals>.decorator.<locals>.is_async"
TRACKED_FUNCS = frozenset({TARGET_FUNC, IS_ASYNC_FUNC})

QUESTION = """\
During the pytest run identified by the test id \
`jinja_qa/async_utils_wrapper_s6_calls/files/testcase.py::TestAsyncUtilsWrapperCalls::test_direct_wrapper_dispatch_batch`, \
report the **executed_path** for the cross-function line trace while the target \
function is active.

The target function is `jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper` \
defined in `src/jinja2/async_utils.py` (the `def wrapper` statement begins at line 39 in that \
file; CPython's `call` events for this nested function are reported at line 37, the first \
`@wraps` decorator line immediately above `def wrapper`). \
The test calls each produced `wrapper` callable directly many times with programmatically \
built arguments.

**Tracked functions** (only these two; use the dotted qualname format `module.qualname`, \
for example `jinja2.async_utils.async_variant.<locals>.decorator.<locals>.is_async`):

1. `jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper`
2. `jinja2.async_utils.async_variant.<locals>.decorator.<locals>.is_async`

**Wrapper activation window:** a wrapper frame is **active** from its `call` event whose \
qualified name is `jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper` \
(reported at line 37 in `src/jinja2/async_utils.py`) until the matching `return` event for \
that same frame (the `return` whose qualified name is \
`jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper`). While at least one \
wrapper frame is active, nested calls to `is_async` may occur; those nested frames are also \
inside the window until they return.

**Inclusion rule:** collect every `line` trace event (exclude `call`, `return`, and \
`exception` events) whose qualified name is one of the tracked functions above and whose \
repo-relative file path is exactly `src/jinja2/async_utils.py`, whenever at least one wrapper \
frame is active as defined above. Include `line` events inside nested `is_async` executions. \
Exclude `line` events that occur only while no wrapper frame is active (for example during \
`async_variant` / `decorator` setup before the test invokes a wrapper). The `def wrapper` line \
(39) and the `def is_async` lines (23 or 28) never appear because they only emit `call` events, \
not `line` events. Line 23 is the body of `is_async` when the sync function uses \
`pass_environment`; line 28 is the body for the other pass styles and for plain functions.

**Line numbers** are absolute, 1-based, and refer to `src/jinja2/async_utils.py` as checked \
into this repository. For a multi-line statement, the executed `line` event is reported on \
the line where that statement begins.

**Ordering:** preserve the chronological order of qualifying `line` events exactly as traced \
across the entire pytest run. Do not sort, deduplicate, or collapse consecutive duplicate \
entries.

Each `executed_path` element is an object with three keys:

- `file`: repo-relative path (`str`), always the exact string `src/jinja2/async_utils.py`.
- `func`: fully qualified name (`str`) as traced, e.g. \
`jinja2.async_utils.async_variant.<locals>.decorator.<locals>.wrapper`.
- `line`: 1-based line number (`int`) in `src/jinja2/async_utils.py`.

Return JSON with top-level key `executed_path` whose value is the list described above.\
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


def _parse_trace_events(trace_log: Path) -> list[tuple[str, str, int, str]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[str, str, int, str]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
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
            )
        )

    if not events:
        raise SystemExit(f"ERROR: no trace events in {TARGET_REL_FILE} from {trace_log}")

    target_events = [
        e
        for e in events
        if e[1] == TARGET_FUNC and e[3] in {"call", "line", "return", "exception"}
    ]
    if not target_events:
        raise SystemExit(f"ERROR: zero trace events for target function {TARGET_FUNC}")

    wrapper_calls = [
        e for e in events if e[1] == TARGET_FUNC and e[3] == "call" and e[2] == WRAPPER_CALL_LINE
    ]
    if not wrapper_calls:
        raise SystemExit(f"ERROR: zero wrapper def-line call events for {TARGET_FUNC}")

    return events


def _compute_executed_path(
    events: list[tuple[str, str, int, str]],
) -> list[dict[str, object]]:
    wrapper_active = 0
    path: list[dict[str, object]] = []

    for rel_file, func, line, event in events:
        if event == "call":
            if func == TARGET_FUNC and line == WRAPPER_CALL_LINE:
                wrapper_active += 1
        elif event == "line":
            if wrapper_active > 0 and func in TRACKED_FUNCS:
                path.append({"file": rel_file, "func": func, "line": line})
        elif event in ("return", "exception"):
            if func == TARGET_FUNC:
                if wrapper_active == 0:
                    raise SystemExit(
                        "ERROR: wrapper return/exception while no wrapper frame is active"
                    )
                wrapper_active -= 1

    if wrapper_active != 0:
        raise SystemExit(
            f"ERROR: unbalanced wrapper stack, {wrapper_active} frames still active"
        )

    if not path:
        raise SystemExit("ERROR: executed_path is empty")

    wrapper_line_events = [e for e in events if e[1] == TARGET_FUNC and e[3] == "line"]
    distinct_wrapper_lines = {line for _, _, line, _ in wrapper_line_events}
    if len(wrapper_line_events) < 40:
        raise SystemExit(
            f"ERROR: expected at least 40 wrapper line events, found {len(wrapper_line_events)}"
        )
    if len(distinct_wrapper_lines) < 4:
        raise SystemExit(
            f"ERROR: expected at least 4 distinct wrapper lines, found {len(distinct_wrapper_lines)}"
        )

    call_events = [e for e in events if e[3] == "call"]
    distinct_call_funcs = {func for _, func, _, _ in call_events}
    if len(call_events) < 10:
        raise SystemExit(f"ERROR: expected at least 10 call events, found {len(call_events)}")
    if len(distinct_call_funcs) < 2:
        raise SystemExit(
            f"ERROR: expected at least 2 distinct traced call functions, found {len(distinct_call_funcs)}"
        )

    if len(path) < 40:
        raise SystemExit(f"ERROR: expected at least 40 executed_path entries, found {len(path)}")

    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    executed_path = _compute_executed_path(events)

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}],
        },
        "oracle_answer": {
            "executed_path": executed_path,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(executed_path)} executed_path entries to {args.out}")


if __name__ == "__main__":
    main()
