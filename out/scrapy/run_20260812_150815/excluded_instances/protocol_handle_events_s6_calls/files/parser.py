from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/core/http2/protocol.py"
TARGET_FUNC = "scrapy.core.http2.protocol.H2ClientProtocol._handle_events"
INVOCATION = 2
TRACKED_FUNCS = (
    "scrapy.core.http2.protocol.H2ClientProtocol.connection_terminated",
    "scrapy.core.http2.protocol.H2ClientProtocol.data_received",
    "scrapy.core.http2.protocol.H2ClientProtocol.response_received",
    "scrapy.core.http2.protocol.H2ClientProtocol.settings_acknowledged",
    "scrapy.core.http2.protocol.H2ClientProtocol.stream_ended",
    "scrapy.core.http2.protocol.H2ClientProtocol.stream_reset",
    "scrapy.core.http2.protocol.H2ClientProtocol.window_updated",
)
TRACKED_SET = set(TRACKED_FUNCS)

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_events(trace_path: Path) -> list[tuple[str, str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, str]] = []
    target_event_count = 0
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_event_count += 1
        if func == TARGET_FUNC or func in TRACKED_SET:
            events.append((func, event))

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def build_answer(events: list[tuple[str, str]]) -> dict[str, object]:
    invocation = 0
    active_invocation: int | None = None
    direct_frame_stack: list[str] = []
    ordered_calls: list[str] = []

    for func, event in events:
        if func == TARGET_FUNC:
            if event == "call":
                invocation += 1
                active_invocation = invocation
                direct_frame_stack.clear()
            elif event == "return" and active_invocation is not None:
                if direct_frame_stack:
                    fail("target returned while a tracked callee frame was still active")
                active_invocation = None
            continue

        if active_invocation is None:
            continue
        if event == "call":
            if active_invocation == INVOCATION and not direct_frame_stack:
                ordered_calls.append(func)
            direct_frame_stack.append(func)
        elif event == "return":
            if not direct_frame_stack or direct_frame_stack[-1] != func:
                fail(f"unbalanced tracked return event for {func}")
            direct_frame_stack.pop()

    if invocation < INVOCATION:
        fail(f"trace has only {invocation} target invocations; need {INVOCATION}")
    if not ordered_calls:
        fail(f"target invocation {INVOCATION} has zero direct tracked calls")

    missing = sorted(TRACKED_SET.difference(ordered_calls))
    if missing:
        fail(
            "target invocation "
            f"{INVOCATION} did not call every configured handler: {missing}"
        )

    return {
        "function_call_order": [
            {"file": TARGET_FILE, "func": func} for func in ordered_calls
        ]
    }


def question_text() -> str:
    tracked = ", ".join(f"`{func}`" for func in TRACKED_FUNCS)
    return (
        "Run the single pytest test "
        "`scrapy_qa/protocol_handle_events_s6_calls/files/testcase.py::"
        "ProtocolEventDispatchTest::test_generated_frames_via_data_received`. "
        "During that test, consider "
        "`scrapy.core.http2.protocol.H2ClientProtocol._handle_events` in "
        "`scrapy/core/http2/protocol.py`. What is the exact ordered sequence of "
        "direct calls that its second invocation makes to this tracked set of "
        f"functions: {tracked}? An invocation is one Python `call` trace event "
        "for the target function, counted 1-based in chronological trace-event "
        "emission order during this test. Thus, the requested invocation begins "
        "at the second such target `call` event and ends at its matching `return` "
        "event. Include a call only when its Python `call` event occurs with that "
        "second target invocation's frame as its immediate caller and its function "
        "is one of the seven names in the tracked set. Do not include the target's "
        "own call, transitive or nested calls made by a handler, calls to any "
        "function outside the tracked set, built-ins, or comprehension frames. "
        "Preserve every qualifying call, including repetitions. If a listed "
        "generator or coroutine produced another `call` event when resumed and "
        "the target frame were again its immediate caller, that event would be "
        "included as another repeated entry. Order entries by Python trace-event "
        "emission order; log timestamps are irrelevant, and even if timestamps "
        "tie, retain file order. Do not sort or deduplicate. Function identity is "
        "the exact dotted `module.Class.method` or `module.function` qualname; for "
        "example, `demo.worker.Job.run`. Return exactly a JSON object with the "
        "single key `function_call_order`. Its value must be a JSON array in that "
        "order, where every element is an object with exactly two keys: `file`, a "
        "JSON string equal to the forward-slash repository-relative path "
        "`scrapy/core/http2/protocol.py`, and `func`, a JSON string containing the "
        "exact dotted function identity. Use the function strings exactly as "
        "listed in the tracked set, without `repr()` quoting or abbreviation. No "
        "line numbers, local values, null placeholders, or additional keys are "
        "included; an absence of qualifying calls would be represented by an "
        "empty JSON array."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    answer = build_answer(parse_events(Path(args.trace_log)))
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": question_text(),
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
