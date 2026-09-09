#!/usr/bin/env python3
"""Parse trace log and emit oracle.json for inspect_render_s6_calls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TARGET_FILE = "rich/_inspect.py"
TARGET_FUNC = "rich._inspect.Inspect._render"
TARGET_ENTRY_LINE = 125
INVOCATION_INDEX = 1  # 1-based

TRACKED_FUNCS = (
    "rich._inspect.Inspect._render.<locals>.safe_getattr",
    "rich._inspect.Inspect._get_signature",
    "rich._inspect.Inspect._get_formatted_doc",
)

_EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _repo_relative(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = "/testbed/"
    if marker in normalized:
        return normalized.split(marker, 1)[1]
    idx = normalized.find(TARGET_FILE)
    if idx >= 0:
        return normalized[idx:]
    return normalized


def _parse_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.is_file():
        raise SystemExit(f"Trace log not found: {trace_path}")

    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise SystemExit(f"Trace log is empty: {trace_path}")

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        match = _EVENT_RE.search(line)
        if not match:
            continue
        if TARGET_FILE not in _repo_relative(match.group("file")):
            continue

        event = match.group("event")
        retval: str | None = None
        if event == "return":
            retval_marker = " retval="
            start = line.find(retval_marker)
            if start >= 0:
                start += len(retval_marker)
                end = line.find(" locals=", start)
                if end < 0:
                    end = len(line)
                retval = line[start:end]

        events.append(
            {
                "file": TARGET_FILE,
                "lineno": int(match.group("lineno")),
                "func": match.group("func"),
                "event": event,
                "retval": retval,
            }
        )

    target_events = [event for event in events if event["func"] == TARGET_FUNC]
    if not target_events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )
    return events


def _invocation_bounds(
    events: list[dict[str, Any]], invocation_index: int
) -> tuple[int, int]:
    entry_indices = [
        index
        for index, event in enumerate(events)
        if event["func"] == TARGET_FUNC
        and event["event"] == "call"
        and event["lineno"] == TARGET_ENTRY_LINE
    ]
    if len(entry_indices) < invocation_index:
        raise SystemExit(
            f"Expected at least {invocation_index} invocation(s) of {TARGET_FUNC}, "
            f"found {len(entry_indices)}"
        )

    start = entry_indices[invocation_index - 1]
    end: int | None = None
    for index in range(start + 1, len(events)):
        event = events[index]
        if (
            event["func"] == TARGET_FUNC
            and event["event"] == "return"
            and event["retval"] == "None"
        ):
            end = index
            break

    if end is None:
        raise SystemExit(
            f"Could not find generator completion return for invocation "
            f"{invocation_index} of {TARGET_FUNC}"
        )
    return start, end


def _function_call_order(
    events: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, str]]:
    tracked = set(TRACKED_FUNCS)
    order: list[dict[str, str]] = []
    for event in events[start : end + 1]:
        if event["event"] == "call" and event["func"] in tracked:
            order.append({"file": TARGET_FILE, "func": event["func"]})
    return order


def _build_question() -> str:
    tracked_list = "\n".join(f"- `{name}`" for name in TRACKED_FUNCS)
    return (
        "Category S6_InterProceduralCFG (tracked function call order).\n"
        "\n"
        "Test scope: pytest id "
        "`rich_qa/inspect_render_s6_calls/files/testcase.py::"
        "TestInspectRenderCalls::test_render_interprocedural_calls` — the "
        "answer covers exactly that single test method's one execution.\n"
        "\n"
        "Target: `rich._inspect.Inspect._render` in repo-relative file "
        "`rich/_inspect.py` (the method begins at line 125). The target is a "
        "generator function.\n"
        "\n"
        "Function identity format: every reported `func` value is the dotted "
        "qualified name `module.Class.method` (or `module.Class.method."
        "<locals>.nested` for nested functions), for example "
        "`rich.console.Console.print`.\n"
        "\n"
        "Invocation counting for the target: consider only `call` events whose "
        f"`func` is exactly `{TARGET_FUNC}` and whose line number is "
        f"{TARGET_ENTRY_LINE}. Number those calls chronologically starting at "
        "1. Invocation 1 is the earliest such call during the test run.\n"
        "\n"
        "Invocation span: `_render` yields multiple renderables. In CPython "
        "`sys.settrace`, each `yield` emits a `return` event carrying the "
        "yielded value, and resuming the generator emits another `call` event "
        "at the next executed line. Those generator `call`/`return` events on "
        "`_render` itself belong to the same logical invocation. Invocation *k* "
        "starts at its entry `call` (line 125 above) and ends at the first "
        "subsequent `return` event for `_render` whose `retval` is exactly the "
        "text `None` (generator exhaustion / StopIteration).\n"
        "\n"
        "Tracked functions (exact qualified names):\n"
        f"{tracked_list}\n"
        "\n"
        "Inclusion rule: include every `call` trace event whose `func` is "
        "exactly one of the tracked functions listed above, occurring "
        "chronologically between the start and end of invocation 1 of "
        "`_render` as defined above (inclusive). Count nested and repeated "
        "calls; do not deduplicate; ignore `line`, `return`, and `exception` "
        "events for ordering; ignore calls to any function not in the tracked "
        "list (including other helpers in `rich/_inspect.py` such as "
        "`sort_items`).\n"
        "\n"
        "Ordering: sort key is trace chronological order (the order events "
        "appear in a single `sys.settrace` log). No secondary tie-breaker is "
        "needed.\n"
        "\n"
        "File field: every object's `file` value is the repo-relative path "
        f"`{TARGET_FILE}` (the file where each tracked function is defined).\n"
        "\n"
        "Question: During invocation 1 of `rich._inspect.Inspect._render`, "
        "what is the exact chronological sequence of `call` events to the "
        "tracked functions listed above?\n"
        "\n"
        "Answer format: a JSON object with exactly one key `function_call_order` "
        "whose value is a JSON array of objects. Each object has exactly two "
        "keys: `file` (string, repo-relative path) and `func` (string, dotted "
        "qualified name)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    events = _parse_trace_events(Path(args.trace_log))
    start, end = _invocation_bounds(events, INVOCATION_INDEX)
    call_order = _function_call_order(events, start, end)

    if len(call_order) < 10:
        raise SystemExit(
            f"Expected at least 10 tracked calls, found {len(call_order)}"
        )

    target_line_events = [
        event for event in events if event["func"] == TARGET_FUNC and event["event"] == "line"
    ]
    all_call_events = [event for event in events if event["event"] == "call"]
    distinct_traced_funcs = {
        event["func"]
        for event in events
        if event["event"] == "call" and event["func"] in set(TRACKED_FUNCS)
    }

    if len(target_line_events) < 40:
        raise SystemExit(
            f"Expected at least 40 line events for target, found {len(target_line_events)}"
        )
    if len({event['lineno'] for event in target_line_events}) < 8:
        raise SystemExit("Expected at least 8 distinct executed lines for target")
    if len(all_call_events) < 10:
        raise SystemExit(
            f"Expected at least 10 call events overall, found {len(all_call_events)}"
        )
    if len(distinct_traced_funcs) < 2:
        raise SystemExit(
            f"Expected at least 2 distinct traced functions, found {len(distinct_traced_funcs)}"
        )

    oracle_answer = {"function_call_order": call_order}
    template_answer = {"function_call_order": [{"file": "str", "func": "str"}]}
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": _build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
