#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/dataclasses/chat_message.py"
TARGET_FUNC = "haystack.dataclasses.chat_message.ChatMessage.to_openai_dict_format"
TARGET_INVOCATION = 2

EVENT_RE = re.compile(
    r"(?P<file>/\S*haystack/dataclasses/chat_message\.py):(?P<line>\d+) "
    r"(?P<traced_func>haystack\.dataclasses\.chat_message\.to_openai_dict_format) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test
`haystack_qa/chat_message_to_openai_dict_format_s1_cfg/files/testcase.py::TestChatMessageOpenAIPath::test_programmatic_mixed_tool_calls`
in a fresh process. During that test method, consider calls to
`haystack.dataclasses.chat_message.ChatMessage.to_openai_dict_format` as defined in
`haystack/dataclasses/chat_message.py`. What is the exact ordered sequence of
executed Python line events inside the function's second invocation?

An invocation is one `call` event for that exact function, counted 1-based in
chronological call-event order during the test; therefore “second” means call
event number 2. Include only `line` events emitted while that invocation's own
frame is active. Exclude its `call`, `return`, and `exception` events, and
exclude all events in properties, library functions, comprehensions, and any
other frames called by it. Preserve event-emission order and preserve repeated
line numbers; do not sort or deduplicate the sequence. Event-emission order is
the total order: events that share a line number remain separate entries in
the order emitted, so no additional tie-breaker is applied.

Line numbers are absolute (not relative offsets), 1-based source line numbers
in the named repository file as it exists for this test. The `def` line,
decorator lines, and docstring lines do not appear: the sequence starts with
the first executable line event after function entry. For a multi-line
statement, call, condition, or nested expression, report the line where the
executed statement or expression begins, as identified by Python's line-event
semantics.

Return exactly one JSON object with the key `executed_path`, whose value is a
list in that chronological order. Every list element must be an object with
exactly these keys: `file` (string), `func` (string), and `line` (integer).
Write those element keys in the order `file`, `func`, `line`.
In every element, `file` must be the repo-relative string
`haystack/dataclasses/chat_message.py`, and `func` must be the fully qualified
string
`haystack.dataclasses.chat_message.ChatMessage.to_openai_dict_format`.
Do not add prose or any other keys."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    raw_trace = trace_path.read_text(encoding="utf-8")
    if not raw_trace.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in raw_trace.splitlines():
        match = EVENT_RE.search(raw_line)
        if match:
            target_events.append(
                {
                    "event": match.group("event"),
                    "line": int(match.group("line")),
                }
            )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation = 0
    executed_path = []
    for event in target_events:
        if event["event"] == "call":
            invocation += 1
        elif event["event"] == "line" and invocation == TARGET_INVOCATION:
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": event["line"],
                }
            )

    if invocation < TARGET_INVOCATION:
        fail(
            f"trace contains only {invocation} invocation(s) of {TARGET_FUNC}; "
            f"need invocation {TARGET_INVOCATION}"
        )
    if not executed_path:
        fail(f"invocation {TARGET_INVOCATION} contains zero line events")

    document = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle with {len(executed_path)} executed line events to {output_path}")


if __name__ == "__main__":
    main()
