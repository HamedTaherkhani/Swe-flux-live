from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/sse.py"
TARGET_FUNC = "fastapi.sse.format_sse_event"
HELPER_FUNC = "fastapi.sse._split_sse_lines"
TRACKED_FUNCS = {TARGET_FUNC, HELPER_FUNC}
SELECTED_INVOCATION = 7
EVENT_RE = re.compile(
    r"(?P<file>\S+fastapi/sse\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test `fastapi_qa/sse_format_sse_event_s6_calls/files/testcase.py::TestFormatSSEEventCalls::test_seeded_batch_with_multiline_fields`. During the seventh invocation of `fastapi.sse.format_sse_event` in `fastapi/sse.py`, what is the exact cross-function executed line path through the tracked functions `fastapi.sse.format_sse_event` and `fastapi.sse._split_sse_lines`?

An invocation is one Python runtime `call` event for exactly `fastapi.sse.format_sse_event`, counted 1-based in chronological order over this test run; select invocation 7. A tracked function's identity is its dotted fully-qualified name in `module.Class.method` or `module.function` form (for example, `sample.widgets.Widget.render`). While the selected target invocation is on the call stack, include every Python `line` event from that target frame and from every nested or transitive invocation of either function in the exact tracked set `{fastapi.sse.format_sse_event, fastapi.sse._split_sse_lines}`. Calls to functions outside that set, including builtins, are excluded. Also exclude all `call`, `return`, and `exception` events. A repeated helper call is included independently, and all of its line events are included. If a tracked generator were present, each runtime generator-resumption `call` event would be a distinct invocation and its line events would be included whenever the selected target remained on the stack; neither tracked function is a generator.

Preserve the runtime's chronological line-event emission order exactly and preserve every duplicate; do not sort or deduplicate. Trace callbacks are sequential, so no secondary tie-breaker is needed. Line numbers are absolute, 1-based source line numbers in the named repository file as it exists for the test. Report the line number supplied by the Python `line` event without AST normalization. For a multi-line statement or expression, this is the line selected by Python's tracing semantics, ordinarily the line on which the currently executed statement or expression begins. Do not synthesize entries for `def`, decorator, signature, or docstring lines: such a line can appear only if Python emits a `line` event for it in an included frame; calling these undecorated functions does not itself add their definition, signature, or docstring lines.

Return exactly one JSON object with the key `executed_path`. Its value is a JSON array in the chronological order above. Every array element must contain exactly three keys: `file`, a repo-relative JSON string (`fastapi/sse.py` here); `func`, the dotted fully-qualified tracked-function JSON string defined above; and `line`, the absolute 1-based JSON integer. There is no `repr()` or `str()` conversion and no null/empty sentinel: strings are emitted directly as JSON strings and line numbers as JSON integers."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_path(trace_path: Path) -> tuple[list[dict[str, str | int]], int, int]:
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_invocations = 0
    selected_active = False
    selected_returned = False
    line_event_count = 0
    path: list[dict[str, str | int]] = []

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None:
                continue
            normalized_file = match.group("file").replace("\\", "/")
            if not normalized_file.endswith(TARGET_FILE):
                continue

            func = match.group("func")
            if func not in TRACKED_FUNCS:
                continue
            event = match.group("event")
            if func == TARGET_FUNC:
                target_events += 1

            if func == TARGET_FUNC and event == "call":
                target_invocations += 1
                if target_invocations == SELECTED_INVOCATION:
                    if selected_active or selected_returned:
                        fail("selected invocation state is inconsistent")
                    selected_active = True

            if selected_active and event == "line":
                path.append(
                    {
                        "file": TARGET_FILE,
                        "func": func,
                        "line": int(match.group("line")),
                    }
                )
                line_event_count += 1

            if (
                selected_active
                and func == TARGET_FUNC
                and event == "return"
            ):
                selected_active = False
                selected_returned = True

    if target_events == 0:
        fail(f"trace log contains zero events for {TARGET_FUNC}")
    if target_invocations < SELECTED_INVOCATION:
        fail(
            f"expected invocation {SELECTED_INVOCATION}, "
            f"found only {target_invocations}"
        )
    if selected_active or not selected_returned:
        fail("selected target invocation did not return normally")
    if not path:
        fail("selected invocation contains zero tracked line events")
    if line_event_count < 40:
        fail(
            f"selected invocation is too short: {line_event_count} line events"
        )
    if len({(item["func"], item["line"]) for item in path}) < 8:
        fail("selected invocation covered fewer than 8 distinct tracked lines")
    if not any(item["func"] == HELPER_FUNC for item in path):
        fail(f"selected invocation contains zero line events for {HELPER_FUNC}")

    return path, target_invocations, line_event_count


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    executed_path, invocation_count, line_count = parse_path(arguments.trace_log)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    with arguments.out.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True)
        output_file.write("\n")

    print(
        f"Wrote {line_count} selected line events from "
        f"{invocation_count} target invocations to {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
