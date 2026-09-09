#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "docs_src/websockets_/tutorial003_py310.py"
TARGET_FUNC = "docs_src.websockets_.tutorial003_py310.websocket_endpoint"
TRACKED_FUNCTIONS = (
    (TARGET_FILE, "docs_src.websockets_.tutorial003_py310.ConnectionManager.__init__"),
    (TARGET_FILE, "docs_src.websockets_.tutorial003_py310.ConnectionManager.broadcast"),
    (TARGET_FILE, "docs_src.websockets_.tutorial003_py310.ConnectionManager.connect"),
    (TARGET_FILE, "docs_src.websockets_.tutorial003_py310.ConnectionManager.disconnect"),
    (
        TARGET_FILE,
        "docs_src.websockets_.tutorial003_py310.ConnectionManager.send_personal_message",
    ),
    (TARGET_FILE, "docs_src.websockets_.tutorial003_py310.get"),
    (TARGET_FILE, TARGET_FUNC),
)

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_events(trace_path):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            events.append((match.group("func"), match.group("event")))

    if not any(func == TARGET_FUNC for func, _event in events):
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if not any(func == TARGET_FUNC and event == "call" for func, event in events):
        fail(f"trace contains no call event for target function {TARGET_FUNC}")
    return events


def build_question():
    tracked_lines = "\n".join(
        f"- `{{\"file\": \"{file}\", \"func\": \"{func}\"}}`"
        for file, func in TRACKED_FUNCTIONS
    )
    return f"""Run the pytest test `fastapi_qa/tutorial003_py310_websocket_endpoint_m6_calls/files/testcase.py::TestWebSocketEndpointRuntime::test_dynamic_function_coverage` and determine dynamic function coverage for the direct exercise of `{TARGET_FUNC}` in `{TARGET_FILE}` (the endpoint defined on lines 72-81).

The tracked function set is exactly:
{tracked_lines}

A tracked function is covered if at least one invocation of that exact function begins during the named test method, whether it is invoked directly by the test, directly by another listed function, or transitively through any other frame. Merely remaining on the stack while some other function runs does not cover that other function. Calls to functions outside the listed set, including builtins and comprehension frames, are ignored. An invocation means the initial entry caused by a function call; count invocations 1-based in chronological call-event order when deciding whether at least one exists. Repeated and recursive invocations still contribute only one covered-set entry. Resuming a suspended generator or coroutine is part of its existing invocation, not a new invocation, and likewise does not create a duplicate entry.

Return exactly one JSON object with key `covered_functions`. Its value is a JSON list of objects, each having exactly the string keys `file` and `func`. Function identity uses the complete dotted Python module and qualified name, for example `package.module.Widget.run`; file identity uses the repository-relative POSIX path. Include each covered tracked function exactly once, and include no uncovered function. Sort the list in ascending lexicographic order first by `file`, then by `func`, comparing Unicode code points; these fields are a complete tie-breaker because duplicates are removed. Serialize the paths and names as ordinary JSON strings, with no `repr()` wrapping or added prefixes."""


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    events = parse_events(Path(args.trace_log))
    called = {func for func, event in events if event == "call"}
    covered = [
        {"file": file, "func": func}
        for file, func in sorted(TRACKED_FUNCTIONS)
        if func in called
    ]
    if not covered:
        fail("computed covered function set is empty")

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"covered_functions": covered},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
