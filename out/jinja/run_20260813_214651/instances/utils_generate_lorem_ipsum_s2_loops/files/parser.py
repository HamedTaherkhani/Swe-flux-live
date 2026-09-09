#!/usr/bin/env python3
"""Parse trace logs for generate_lorem_ipsum while-loop iteration count."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/utils.py"
TARGET_FUNC = "jinja2.utils.generate_lorem_ipsum"
LOOP_HEADER_LINE = 371
LOOP_BODY_LINE = 372
TARGET_INVOCATION = 1

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def harvest_loop_iteration_count(trace_log: Path) -> int:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    target_events = 0
    invocation_index = 0
    in_target_invocation = False
    iteration_count = 0

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]

        if event == "call":
            invocation_index += 1
            in_target_invocation = invocation_index == TARGET_INVOCATION
            if in_target_invocation:
                iteration_count = 0
        elif event == "line" and in_target_invocation:
            if int(parsed["lineno"]) == LOOP_BODY_LINE:
                iteration_count += 1
        elif event == "return" and in_target_invocation:
            in_target_invocation = False

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if invocation_index < TARGET_INVOCATION:
        raise SystemExit(
            f"Trace contains {invocation_index} invocations of {TARGET_FUNC}, "
            f"but invocation {TARGET_INVOCATION} was required"
        )

    return iteration_count


def build_question() -> str:
    return (
        "Consider the single test method "
        "`jinja_qa/utils_generate_lorem_ipsum_s2_loops/files/testcase.py::"
        "TestGenerateLoremIpsumLoops::test_while_loop_word_selection`.\n\n"
        "That test calls `generate_lorem_ipsum` **directly** from "
        "`jinja2.utils` (imported from `jinja2.utils.generate_lorem_ipsum`).\n\n"
        "Target function: `jinja2.utils.generate_lorem_ipsum` (the function "
        f"whose `def` begins at line 353 of `{TARGET_FILE}`).\n\n"
        "Target loop: the `while True:` header on line "
        f"{LOOP_HEADER_LINE} of `{TARGET_FILE}`. An **iteration** of this "
        "loop is one execution of the loop body's first physical line (line "
        f"{LOOP_BODY_LINE}: `word = choice(words)`). Count iterations using "
        "`sys.settrace` `line` events whose file path contains "
        f"`{TARGET_FILE}`, whose qualified name is exactly `{TARGET_FUNC}`, "
        f"and whose line number equals {LOOP_BODY_LINE}.\n\n"
        "**Invocation** means one `call` trace event for "
        f"`{TARGET_FUNC}` during the test run, numbered chronologically "
        "starting at 1 in the order those `call` events appear. The matching "
        "invocation is the half-open interval from that `call` event up to "
        "(but not including) the next `return` event for the same qualified "
        "name. `exception` events are out of scope.\n\n"
        f"Report the iteration count for invocation {TARGET_INVOCATION} only: "
        "the total number of times line "
        f"{LOOP_BODY_LINE} executed while invocation {TARGET_INVOCATION} is "
        "active.\n\n"
        f"Line numbers are absolute, 1-based, in `{TARGET_FILE}` as it exists "
        "in the repository. For multi-line statements, a `line` event fires "
        "on the line where that statement begins.\n\n"
        "Return JSON with exactly one top-level key: `loop_iteration_count` "
        "(integer)."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    loop_iteration_count = harvest_loop_iteration_count(args.trace_log)

    oracle_answer = {"loop_iteration_count": loop_iteration_count}
    template_answer = {"loop_iteration_count": "int"}

    payload = {
        "question_kind": "S2_Loops",
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
