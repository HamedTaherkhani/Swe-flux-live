#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scripts/doc_parsing_utils.py"
TARGET_FUNC = "scripts.doc_parsing_utils.extract_header_permalinks"
OBSERVATION_LINE = 155

QUESTION = """Run only the pytest test `fastapi_qa/doc_parsing_utils_extract_header_permalinks_m3_state/files/testcase.py::TestGeneratedTranslation::test_generated_fenced_sections`. During that test run, consider every invocation of `scripts.doc_parsing_utils.extract_header_permalinks` in `scripts/doc_parsing_utils.py`. An invocation is one call of that exact function, numbered from 1 in chronological order; observations from all invocations count.

At every execution of line 155 in that exact function, observe the local variable `headers` immediately before the statement on that line executes. Line numbers are absolute, 1-based line numbers in the named repository file. A line event occurs immediately before the statement or expression beginning on that line executes; for a multi-line statement it belongs to the line where the statement or expression begins. Only executions of line 155 count, so the function's `def` line, decorator lines, docstring lines, and all other lines are excluded.

For each observation, take the exact standard Python `repr(headers)` of the whole list at that point, including the standard Python representations of all nested dictionaries and their values. Do not truncate or otherwise normalize the representation; strings retain quotes and escapes, and `None` and booleans, if present, use Python spellings rather than JSON spellings. Every counted observation has a value, so there is no missing-value or JSON-null convention.

Return `oracle_answer` with exactly the shape `{"unique_values": [<string>, ...]}`. Remove duplicates after computing the complete `repr()` strings, then sort the remaining strings in ascending lexicographic order by Unicode code point (the same ordering as Python's `sorted()` on strings), with no secondary tie-breaker needed because duplicates have been removed. Each array element is the `repr()` result stored as a JSON string."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*scripts/doc_parsing_utils\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw_line: str) -> dict[str, str]:
    marker = " locals="
    if marker not in raw_line:
        fail("target trace event has no locals mapping")
    encoded = raw_line.rpartition(marker)[2]
    try:
        value = ast.literal_eval(encoded)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals mapping: {exc}")
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        fail("target locals mapping did not contain string keys and repr strings")
    return value


def harvest(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocations = 0
    frame_active = False
    current_locals: dict[str, str] = {}
    observed_values: list[str] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))
        changed_locals = parse_locals(raw_line)

        if event == "call":
            if frame_active:
                fail("overlapping target invocations are unsupported")
            invocations += 1
            frame_active = True
            current_locals = {}

        if not frame_active:
            fail("target event occurred outside an active invocation")

        current_locals.update(changed_locals)

        if event == "line" and line_number == OBSERVATION_LINE:
            if "headers" not in current_locals:
                fail("an observation on line 155 lacks the local variable headers")
            observed_values.append(current_locals["headers"])

        if event in {"return", "exception"}:
            frame_active = False
            current_locals = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocations == 0:
        fail(f"trace contains zero invocations of {TARGET_FUNC}")
    if frame_active:
        fail("trace ended during an active target invocation")
    if not observed_values:
        fail("trace contains no observations on line 155")

    unique_values = sorted(set(observed_values))
    if len(unique_values) < 8:
        fail(f"expected at least 8 distinct states, found {len(unique_values)}")
    return {"unique_values": unique_values}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": harvest(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    arguments.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
