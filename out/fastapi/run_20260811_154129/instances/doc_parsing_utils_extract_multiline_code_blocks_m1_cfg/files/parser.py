from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/doc_parsing_utils.py"
TARGET_FUNC = "scripts.doc_parsing_utils.extract_multiline_code_blocks"
EVENT_RE = re.compile(
    r"(?P<file>\S+scripts/doc_parsing_utils\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test `fastapi_qa/doc_parsing_utils_extract_multiline_code_blocks_m1_cfg/files/testcase.py::TestDocumentParsingControlFlow::test_generated_documents_follow_distinct_fence_paths`. Across the whole execution of that test, what is the sorted set of source line numbers in `scripts/doc_parsing_utils.py` that execute in frames of the function `scripts.doc_parsing_utils.extract_multiline_code_blocks`?

An invocation means one runtime `call` event for that exact function, numbered 1-based in chronological order; include the union of line events from every invocation caused by the test, including invocations reached indirectly through other functions. An executed line is an absolute, 1-based line number in the named repository file for which Python emits a runtime `line` event while that exact function's frame is active. Ignore `call`, `return`, and `exception` events, and ignore events in every other function, including calls made by the target. The `def` line does not count merely because the function is called; a decorator or docstring line would count only if it produced a `line` event in the target frame. For a multi-line statement or expression, count the line on which each executed statement or subexpression begins when Python attributes a `line` event to it; do not infer that physical continuation lines executed merely because they are part of the same textual statement.

Return exactly one JSON object with the key `covered_lines`. Its value must be a JSON array of integers containing the union of those line numbers across all invocations, deduplicated and sorted in strictly ascending numeric order. For example, repeated runtime events on hypothetical lines 7 and 9 would be serialized as `{"covered_lines":[7,9]}` regardless of their chronological order."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_events(trace_path: Path) -> tuple[list[int], list[tuple[int, ...]]]:
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    all_lines: list[int] = []
    invocations: list[tuple[int, ...]] = []
    current_lines: list[int] | None = None
    target_events = 0

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None:
                continue
            if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
                continue
            if match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            event = match.group("event")
            line_number = int(match.group("line"))

            if event == "call":
                if current_lines is not None:
                    fail("encountered a nested target call before the prior invocation ended")
                current_lines = []
            elif event == "line":
                if current_lines is None:
                    fail("encountered a target line event outside an invocation")
                current_lines.append(line_number)
                all_lines.append(line_number)
            elif event == "return":
                if current_lines is None:
                    fail("encountered a target return event outside an invocation")
                invocations.append(tuple(current_lines))
                current_lines = None

    if target_events == 0:
        fail(f"trace log contains zero events for {TARGET_FUNC}")
    if current_lines is not None:
        fail("trace log ended before the final target invocation returned")
    if len(invocations) < 3:
        fail(f"expected at least 3 target invocations, found {len(invocations)}")
    if any(not lines for lines in invocations):
        fail("every target invocation must contain at least one line event")
    if len(set(invocations)) < 3:
        fail("expected at least 3 target invocations with distinct line-event paths")
    if len(all_lines) < 60:
        fail(f"expected at least 60 target line events, found {len(all_lines)}")

    covered_lines = sorted(set(all_lines))
    if len(covered_lines) < 25:
        fail(f"expected at least 25 distinct covered lines, found {len(covered_lines)}")
    return covered_lines, invocations


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    covered_lines, invocations = parse_events(arguments.trace_log)
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    with arguments.out.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True)
        output_file.write("\n")

    print(
        f"Wrote oracle with {len(covered_lines)} covered lines "
        f"from {len(invocations)} invocations to {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
