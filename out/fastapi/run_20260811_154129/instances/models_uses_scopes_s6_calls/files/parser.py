#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "fastapi/dependencies/models.py"
TARGET_FUNC = "fastapi.dependencies.models._uses_scopes"
TRACKED_FUNCS = {
    "fastapi.dependencies.models._impartial",
    "fastapi.dependencies.models._is_security_scheme",
    "fastapi.dependencies.models._unwrapped_call",
    "fastapi.dependencies.models._uses_scopes",
}

QUESTION = """Run only the pytest test `fastapi_qa/models_uses_scopes_s6_calls/files/testcase.py::TestUsesScopesCallOrder::test_seeded_dependency_fanout`. During that test run, consider the first invocation of `fastapi.dependencies.models._uses_scopes` in `fastapi/dependencies/models.py`.

Report the exact ordered sequence of Python `sys.settrace` `call` events for this exact tracked set: `fastapi.dependencies.models._uses_scopes`, `fastapi.dependencies.models._is_security_scheme`, `fastapi.dependencies.models._unwrapped_call`, and `fastapi.dependencies.models._impartial`. Function identity is `frame.f_globals["__name__"] + "." + frame.f_code.co_qualname`, giving the dotted `module.Class.method` or `module.function` form; for example, an unrelated function could be `sample.widgets.build`.

An invocation means one `call` event for the named function, counted globally in chronological order starting at 1; therefore the requested invocation is the first such event during this test. Treat that invocation as active from its initiating `call` event through the matching `return` event of that same synchronous frame.

Include the initiating `call` event itself and every later `call` event for a function in the exact tracked set whenever it occurs while the requested target invocation is on the stack. This is a transitive rule: qualifying calls nested at any depth count, not only calls made directly by the target frame. Retain every repeated call and, if a tracked generator or coroutine frame resumes and emits another `call` event, retain that event too. Exclude calls to every function outside the exact tracked set, including builtins and the `_uses_scopes` generator-expression comprehension frame. Return and exception events are not output items, and collection stops at the matching target-frame return.

Preserve chronological event order, earliest first; the serial event order is the complete tie-breaker. Do not sort and do not deduplicate.

Return `oracle_answer` with exactly the shape `{"function_call_order": [{"file": <string>, "func": <string>}]}`. Each `file` is the repository-relative POSIX path formed by removing the `/testbed/` repository-root prefix from that event frame's absolute filename. Each `func` is the dotted identity defined above. Both are ordinary JSON strings with no `repr()` or `str()` transformation. The sequence is non-empty, so neither an empty-value convention nor JSON `null` applies."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*fastapi/dependencies/models\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
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
        fail(f"event frame filename is not under {prefix}: {raw_file!r}")
    relative_file = raw_file[len(prefix) :]
    if relative_file != TARGET_FILE:
        fail(f"unexpected event frame file: {relative_file}")
    return relative_file


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    events = read_events(trace_path)
    start = next(
        (
            index
            for index, event in enumerate(events)
            if event["func"] == TARGET_FUNC and event["event"] == "call"
        ),
        None,
    )
    if start is None:
        fail(f"trace contains zero call events for {TARGET_FUNC}")

    frame_depth = 0
    invocation_events: list[dict[str, object]] = []
    found_matching_return = False
    for event in events[start:]:
        invocation_events.append(event)
        if event["event"] == "call":
            frame_depth += 1
        elif event["event"] == "return":
            frame_depth -= 1
            if frame_depth < 0:
                fail("encountered an unmatched return event")
            if frame_depth == 0:
                found_matching_return = True
                break

    if not found_matching_return:
        fail("requested target invocation has no matching return event")

    call_order = [
        {
            "file": repository_relative_file(event["file"]),
            "func": str(event["func"]),
        }
        for event in invocation_events
        if event["event"] == "call" and event["func"] in TRACKED_FUNCS
    ]
    if len(call_order) < 10:
        fail("requested invocation produced fewer than 10 tracked call events")
    if len({item["func"] for item in call_order}) < 2:
        fail("requested invocation produced fewer than 2 distinct tracked functions")

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
