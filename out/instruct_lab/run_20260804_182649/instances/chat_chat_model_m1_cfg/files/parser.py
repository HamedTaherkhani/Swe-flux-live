#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/chat.py"
TARGET_FUNC = "instructlab.model.chat.chat_model"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> list[int]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocations: list[list[int]] = []
    active: list[int] | None = None

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if active is not None:
                fail("encountered a nested target call before the prior invocation returned")
            active = []
            invocations.append(active)
        elif event == "line":
            if active is None:
                fail("encountered a target line event outside an invocation")
            active.append(int(match.group("line")))
        elif event == "return":
            if active is None:
                fail("encountered a target return event outside an invocation")
            active = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active is not None:
        fail("trace ended while a target invocation was active")
    if len(invocations) < 3:
        fail(f"expected at least 3 target invocations, found {len(invocations)}")
    if any(not lines for lines in invocations):
        fail("one or more target invocations contains zero line events")
    if len({tuple(sorted(set(lines))) for lines in invocations}) < 3:
        fail("expected at least 3 invocations with distinct executed-line sets")

    covered_lines = sorted({line for invocation in invocations for line in invocation})
    if not covered_lines:
        fail("target invocations produced no covered lines")
    return covered_lines


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    covered_lines = parse_trace(Path(args.trace_log))
    question = (
        "Run the single pytest test "
        "`instruct_lab_qa/chat_chat_model_m1_cfg/files/testcase.py::"
        "TestChatCommandPaths::test_cli_dispatches_varied_server_routes` against "
        "this repository. Across the whole test, what is the exact line coverage "
        "of `instructlab.model.chat.chat_model` in "
        "`src/instructlab/model/chat.py`? An invocation means one runtime `call` "
        "event for exactly this function, counted 1-based in chronological order; "
        "the requested coverage is the union of `line` events from every such "
        "invocation during the test, regardless of whether an invocation returns "
        "normally or unwinds with an exception. Count only events whose active "
        "frame is exactly `instructlab.model.chat.chat_model`: exclude call, return, "
        "and exception events, and exclude all events in callers, callees, nested "
        "functions, and other frames. Report absolute 1-based physical line numbers "
        "in the named repository file as it exists for this test. A runtime line "
        "event uses Python's `frame.f_lineno`, which identifies the physical line "
        "where the currently executing statement or expression component begins. "
        "For a multi-line statement, include a continuation line only if Python "
        "emits a line event whose `f_lineno` is that line; do not normalize it to "
        "the first line of the complete statement and do not infer coverage merely "
        "because text spans that line. The function's `def` line is represented by "
        "a call event rather than a line event and therefore does not count; there "
        "are no decorators, and the non-executable docstring line does not count. "
        "Return exactly one JSON object with the single key `covered_lines`. Its "
        "value must be a JSON array of JSON integers containing the set of all "
        "qualifying line numbers, sorted in strictly ascending numeric order with "
        "duplicates removed across and within invocations. For example, hypothetical "
        "events on lines 8, 3, and 8 serialize as `{\"covered_lines\":[3,8]}` "
        "(whitespace is insignificant). Do not use strings, Python `repr`, null, "
        "or omitted values."
    )
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": question,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
