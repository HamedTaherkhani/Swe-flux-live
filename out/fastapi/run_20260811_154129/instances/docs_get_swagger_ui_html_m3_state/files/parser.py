#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any


TARGET_FUNC = "fastapi.openapi.docs.get_swagger_ui_html"
OBSERVATION_LINES = {171, 184}

QUESTION = """Run only the pytest test `fastapi_qa/docs_get_swagger_ui_html_m3_state/files/testcase.py::TestGeneratedSwaggerUI::test_generated_parameter_states`. During that test run, consider every invocation of `fastapi.openapi.docs.get_swagger_ui_html` in `fastapi/openapi/docs.py`. An invocation is one `call` of that exact function, numbered from 1 in chronological order; observations from all invocations count.

At every execution of line 171 or line 184 in that exact function, observe the function frame immediately before the statement on that line executes. For each observation, construct this five-item Python tuple, in order: `(invocation_number, executed_line_number, len(html), tuple(current_swagger_ui_parameters.keys()), key_if_defined_else_None)`. Here `html`, `current_swagger_ui_parameters`, and `key` are the local variables in that frame; `key_if_defined_else_None` is the current value of local `key` when that local exists and is Python `None` otherwise. `tuple(current_swagger_ui_parameters.keys())` uses the dictionary's iteration/insertion order at that observation, without sorting its keys. Thus each state combines multiple locals, and the dictionary is observed after any in-place update that occurred before the counted line.

Line numbers are absolute, 1-based line numbers in the named repository file. An executed-line event occurs immediately before the statement or expression beginning on that line executes; for a multi-line statement it belongs to the line where the statement or expression begins. Only executions of lines 171 and 184 count, so the function's `def` line, decorator lines, docstring lines, and every other line are excluded. Repeated executions count as separate observations before deduplication.

For each constructed tuple, take its exact standard Python `repr()` as the observed string. This is the representation of the whole tuple, including standard Python representations for the nested key tuple and the optional key; do not truncate or otherwise normalize it. Strings retain Python quotes and escapes, and `None` and booleans use Python spellings rather than JSON spellings. For example, the representation of the unrelated tuple `(3, "x")` is the string `"(3, 'x')"`. Every observation produces a string, so no absent value, empty-string sentinel, or JSON `null` is used.

Return `oracle_answer` with exactly the shape `{"unique_values": [<string>, ...]}`; `unique_values` is an array of JSON strings. Remove duplicates only after constructing all complete `repr()` strings across both lines and all invocations. Sort the remaining strings in ascending lexicographic order by Unicode code point, exactly as Python's `sorted()` orders strings. No secondary tie-breaker is needed because duplicates have been removed."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*fastapi/openapi/docs\.py):(?P<line>\d+) "
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


def literal_local(current_locals: dict[str, str], name: str) -> Any:
    if name not in current_locals:
        fail(f"an observation lacks required local variable {name!r}")
    representation = current_locals[name]
    if representation.endswith("..."):
        fail(f"local variable {name!r} has a truncated representation")
    try:
        return ast.literal_eval(representation)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not evaluate repr for local variable {name!r}: {exc}")


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

        if event == "line" and line_number in OBSERVATION_LINES:
            html = literal_local(current_locals, "html")
            parameters = literal_local(current_locals, "current_swagger_ui_parameters")
            if not isinstance(html, str):
                fail("local variable 'html' is not a string")
            if not isinstance(parameters, dict):
                fail("local variable 'current_swagger_ui_parameters' is not a dictionary")
            active_key = (
                literal_local(current_locals, "key") if "key" in current_locals else None
            )
            state = (
                invocations,
                line_number,
                len(html),
                tuple(parameters.keys()),
                active_key,
            )
            observed_values.append(repr(state))

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
        fail(f"trace contains no observations on lines {sorted(OBSERVATION_LINES)}")

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
