#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


QUESTION_KIND = "S6_InterProceduralCFG"
TARGET_FILE = "scrapy/http/response/text.py"
TARGET_FUNC = "scrapy.http.response.text.TextResponse.follow_all"
TRACKED_FUNCS = {
    "scrapy.http.response.text.TextResponse.follow_all",
    "scrapy.http.response.text.TextResponse.follow",
    "scrapy.http.response.text.TextResponse.css",
    "scrapy.http.response.text.TextResponse.xpath",
    "scrapy.http.response.text._url_from_selector",
}

QUESTION = """Run the single pytest test method `TestTextResponseFollowAll.test_mixed_xpath_selectors` in `scrapy_qa/text_follow_all_s6_calls/files/testcase.py`. During the first invocation of `scrapy.http.response.text.TextResponse.follow_all` in `scrapy/http/response/text.py`, what is the exact ordered sequence of tracked Python function-call events?

An invocation means one Python `call` trace event for `scrapy.http.response.text.TextResponse.follow_all`; invocations are numbered from 1 in chronological execution order. Include the call event that begins invocation 1 itself. After that, include calls made directly by that target frame and calls made transitively by its descendants, but only while invocation 1 remains on the call stack. The interval ends at that invocation's matching `return` event. In particular, exclude calls that occur while the iterable returned by `follow_all` is consumed after the target frame has returned.

The exact tracked set is: `scrapy.http.response.text.TextResponse.follow_all`, `scrapy.http.response.text.TextResponse.follow`, `scrapy.http.response.text.TextResponse.css`, `scrapy.http.response.text.TextResponse.xpath`, and `scrapy.http.response.text._url_from_selector`. Exclude every function outside this set, including builtins, library helpers, comprehension frames, and methods inherited from classes other than `TextResponse`. A call means a Python line-tracing `call` event, not merely a call expression in source. Retain every repeated event without deduplication. If a tracked generator were present, each generator resumption that produces a Python `call` event would be retained as another event; resumptions without a `call` event would not add an item.

Order items by the runtime emission order of those `call` events, from earliest to latest; do not sort or deduplicate them. Runtime event order is the sole tie-breaker (wall-clock timestamps are not used). Represent each function as its full dotted identity `module.QualName`, for example `scrapy.http.request.Request.replace`. Represent `file` as the repository-relative POSIX path. Return exactly `{"function_call_order": [{"file": <str>, "func": <str>}, ...]}`; each object must have exactly the two string fields `file` and `func`."""

EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match:
            events.append(match.groupdict())

    target_events = [event for event in events if event["func"] == TARGET_FUNC]
    if not target_events:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")

    active = False
    saw_target_return = False
    answer: list[dict[str, str]] = []
    for event in events:
        func = event["func"]
        event_kind = event["event"]

        if not active:
            if func == TARGET_FUNC and event_kind == "call":
                active = True
            else:
                continue

        if event_kind == "call" and func in TRACKED_FUNCS:
            normalized_file = event["file"].replace("\\", "/")
            if not normalized_file.endswith("/" + TARGET_FILE):
                fail(
                    f"tracked call for {func} came from unexpected file: "
                    f"{event['file']}"
                )
            answer.append({"file": TARGET_FILE, "func": func})

        if func == TARGET_FUNC and event_kind == "return":
            saw_target_return = True
            break

    if not active:
        fail(f"trace has no call event for target function {TARGET_FUNC}")
    if not saw_target_return:
        fail(f"trace has no matching return event for target function {TARGET_FUNC}")
    if not answer:
        fail("target invocation produced an empty tracked call sequence")
    if answer[0]["func"] != TARGET_FUNC:
        fail("tracked call sequence does not begin with the target call")
    return answer


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True, type=Path)
    arg_parser.add_argument("--out", required=True, type=Path)
    args = arg_parser.parse_args()

    try:
        call_order = parse_trace(args.trace_log)
        payload = {
            "question_kind": QUESTION_KIND,
            "question": QUESTION,
            "template_answer": {
                "function_call_order": [{"file": "str", "func": "str"}]
            },
            "oracle_answer": {"function_call_order": call_order},
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
