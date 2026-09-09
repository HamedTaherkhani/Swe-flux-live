#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "fastapi/dependencies/utils.py"
TARGET_FUNC = "fastapi.dependencies.utils.analyze_param"
STATEMENT_LINE = 529
POST_STATEMENT_LINE = 536
OCCURRENCE = 19
VARIABLES = [
    "alias",
    "field",
    "field_info",
    "type_annotation",
    "use_annotation_from_field_info",
]

QUESTION = """Run only the pytest test `fastapi_qa/utils_analyze_param_s3_state/files/testcase.py::TestGeneratedRoute::test_generated_signature_registration`. During that test run, consider `fastapi.dependencies.utils.analyze_param` in `fastapi/dependencies/utils.py`.

What are the values of the local variables `alias`, `field`, `field_info`, `type_annotation`, and `use_annotation_from_field_info` immediately after the statement beginning on line 529 has executed for the 19th time during the test run? Count completed executions of that assignment globally across all invocations of this exact function frame, in chronological order, using 1-based counting. An invocation is one call of this exact function and invocations are ordered chronologically from 1, although the requested count is over assignment completions rather than invocation numbers. Line numbers are absolute, 1-based line numbers in the named repository file. Line 529 begins a multi-line assignment: count it once when the complete assignment, including its multi-line call, finishes. Calls made while evaluating the assignment do not create additional executions. The observation point is after that completion but before line 536 executes.

Report each value as the exact Python `repr()` string at that observation point. For a container, use `repr()` of the whole container rather than separately formatting its elements; thus strings retain quotes, `None` and booleans use Python spellings, and any embedded newline is a real newline character within the JSON string. Every named variable exists at the observation point, so there is no missing-value or JSON-null convention to apply.

Return `oracle_answer` with exactly the shape `{"observed_state": [{"value": <string>, "variable": <string>}]}`. Include one item per named variable, ordered by `variable` in ascending Unicode code-point order. Keep all five items, perform no deduplication, and use the local variable's bare source identifier in `variable`."""


EVENT_RE = re.compile(
    r"(?P<file>/\S*fastapi/dependencies/utils\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)
LOCALS_RE = re.compile(r"locals=(\{.*\})$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(line: str) -> dict[str, str]:
    match = LOCALS_RE.search(line)
    if match is None:
        fail("target trace event has no parseable locals mapping")
    try:
        value = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals mapping: {exc}")
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        fail("target locals mapping did not contain string keys and repr strings")
    return value


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    occurrence = 0
    frame_active = False
    current_locals: dict[str, str] = {}
    observed: dict[str, str] | None = None

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.search(raw_line)
        if event_match is None or event_match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = event_match.group("event")
        line_number = int(event_match.group("line"))
        changed = parse_locals(raw_line)

        if event == "call":
            if frame_active:
                fail("overlapping exact target frames are unsupported")
            frame_active = True
            current_locals = {}

        if not frame_active:
            fail("target event occurred outside an active exact target frame")

        current_locals.update(changed)

        if event == "line" and line_number == POST_STATEMENT_LINE:
            occurrence += 1
            if occurrence == OCCURRENCE:
                missing = [name for name in VARIABLES if name not in current_locals]
                if missing:
                    fail(
                        "observation point lacks requested locals: "
                        + ", ".join(sorted(missing))
                    )
                observed = {name: current_locals[name] for name in VARIABLES}

        if event in {"return", "exception"}:
            frame_active = False
            current_locals = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if occurrence < OCCURRENCE:
        fail(
            f"line {STATEMENT_LINE} executed only {occurrence} times; "
            f"needed occurrence {OCCURRENCE}"
        )
    if observed is None:
        fail("the requested post-statement observation was not captured")

    return {
        "observed_state": [
            {"value": observed[name], "variable": name} for name in sorted(VARIABLES)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    oracle_answer = harvest(arguments.trace_log)
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
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
