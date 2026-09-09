#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "fastapi/routing.py"
TARGET_FUNC = "fastapi.routing.APIRouter.app"
TARGET_DEF_LINE = 2719
INVOCATION = 13
TRACKED_FUNCS = {
    "fastapi.routing.APIRoute.handle",
    "fastapi.routing.APIRoute.matches",
    "fastapi.routing.APIRouter.app",
}

QUESTION = """Run only the pytest test `fastapi_qa/routing_app_s6_calls/files/testcase.py::TestRouterDispatchCallOrder::test_seeded_route_matrix`. During that test run, consider the 13th invocation of `fastapi.routing.APIRouter.app` in `fastapi/routing.py` (the function whose definition begins at absolute, 1-based line 2719).

Report the exact ordered sequence of Python `sys.settrace` `call` events for this tracked set of exact functions: `fastapi.routing.APIRouter.app`, `fastapi.routing.APIRoute.matches`, and `fastapi.routing.APIRoute.handle`. Function identity is formed as `frame.f_globals["__name__"] + "." + frame.f_code.co_qualname`, i.e. `module.Class.method` for these methods; for example, an unrelated method could be `sample.mod.Widget.run`.

An invocation of `fastapi.routing.APIRouter.app` is one newly created coroutine frame entry: count, globally and chronologically from 1, only its `call` event at the function's definition line 2719. A `call` event emitted when that already-created coroutine frame resumes after an `await` does not begin another invocation. The requested invocation remains logically active from that initial entry through suspensions until that same frame's final `return` event.

Include the initial `call` event that starts the requested invocation. Then include every later `call` event for any function in the tracked set whenever it occurs while that logical invocation is active, whether called directly by the target frame or nested/transitively below it. Retain every repeated call. In particular, retain `call` events produced when an existing coroutine or generator frame in the tracked set resumes, but do not reinterpret a resumption of the target as a new invocation. Exclude all calls to functions outside the exact tracked set, including builtins and comprehension frames. Stop at the target frame's final `return`; return and exception events themselves are not list items.

Order items by chronological trace-event order, earliest first. Python dispatches these trace events serially, so this event order is the complete tie-breaker. Do not sort or deduplicate the sequence.

Return `oracle_answer` with exactly the shape `{"function_call_order": [{"file": <string>, "func": <string>}]}`. For every item, `file` is the repository-relative POSIX path obtained by removing the `/testbed/` repository-root prefix from the frame filename, and `func` uses the identity rule above. Both fields are JSON strings; no `repr()` or other value formatting is applied. The sequence is non-empty, so no empty-value or JSON-null convention applies."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*fastapi/routing\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_events(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events: list[dict[str, object]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        events.append(
            {
                "file": match.group("file"),
                "line": int(match.group("line")),
                "func": match.group("func"),
                "event": match.group("event"),
            }
        )

    if not any(event["func"] == TARGET_FUNC for event in events):
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def repository_relative_file(raw_file: object) -> str:
    prefix = "/testbed/"
    if not isinstance(raw_file, str) or not raw_file.startswith(prefix):
        fail(f"target frame filename is not under {prefix}: {raw_file!r}")
    relative_file = raw_file[len(prefix) :]
    if relative_file != TARGET_FILE:
        fail(f"unexpected target frame file: {relative_file}")
    return relative_file


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    events = read_events(trace_path)
    initial_entries = [
        index
        for index, event in enumerate(events)
        if event["func"] == TARGET_FUNC
        and event["event"] == "call"
        and event["line"] == TARGET_DEF_LINE
    ]
    if len(initial_entries) < INVOCATION:
        fail(
            f"found only {len(initial_entries)} initial calls of {TARGET_FUNC}; "
            f"needed invocation {INVOCATION}"
        )

    start = initial_entries[INVOCATION - 1]
    next_start = (
        initial_entries[INVOCATION]
        if len(initial_entries) > INVOCATION
        else len(events)
    )
    invocation_window = events[start:next_start]
    final_returns = [
        index
        for index, event in enumerate(invocation_window)
        if event["func"] == TARGET_FUNC and event["event"] == "return"
    ]
    if not final_returns:
        fail("requested target invocation has no return event")
    invocation_events = invocation_window[: final_returns[-1] + 1]

    call_order = [
        {
            "file": repository_relative_file(event["file"]),
            "func": str(event["func"]),
        }
        for event in invocation_events
        if event["event"] == "call" and event["func"] in TRACKED_FUNCS
    ]
    if not call_order:
        fail("requested invocation produced no tracked call events")
    if len(call_order) < 10 or len({item["func"] for item in call_order}) < 2:
        fail("requested invocation did not produce a rich interprocedural call order")

    return {"function_call_order": call_order}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    oracle_answer = harvest(arguments.trace_log)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
