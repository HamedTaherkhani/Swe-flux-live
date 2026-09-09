from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/cli/starters.py"
TARGET_FUNC = "kedro.framework.cli.starters.new"
PRECEDING_LINE = 394
OBSERVATION_EVENT_LINE = 395
OBSERVATION_OCCURRENCE = 11
VARIABLES = (
    "cookiecutter_args",
    "cookiecutter_context",
    "extra_context",
    "interactive_flow",
    "project_template",
    "prompts_required",
    "selected_tools",
    "telemetry_consent",
    "template_path",
)

EVENT_RE = re.compile(
    r"(?P<file>\S*kedro/framework/cli/starters\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/starters_new_s3_state/files/testcase.py::TestNewProgramState::test_seeded_direct_invocations`
and consider the direct calls it makes to
`kedro.framework.cli.starters.new` in
`kedro/framework/cli/starters.py`.

What are the values of the local variables `cookiecutter_args`,
`cookiecutter_context`, `extra_context`, `interactive_flow`,
`project_template`, `prompts_required`, `selected_tools`,
`telemetry_consent`, and `template_path` immediately after line 394 has
executed for the 11th time during this test run?

Line 394 means the absolute, 1-based source line in the named file as it
exists in the repository. An occurrence is counted each time that line's
assignment statement executes in a frame of the named function, in
chronological order across the whole test run, starting at 1. Calls in which
control flow does not reach line 394 do not count. An invocation means one
call of the named function, numbered from 1 in chronological order, although
the requested point is selected by line-execution occurrence rather than by
invocation number. Observe the state after the assignment on line 394 has
completed and before the multi-line call whose expression begins on line 395
executes. Decorator lines, the `def` line, and the docstring are not line 394
occurrences.

Return exactly one JSON object with the shape
`{"observed_state": [{"value": "...", "variable": "..."}]}`. Include exactly
one item for each of the nine named variables, sorted by `variable` in
ascending Unicode code-point order; do not remove duplicates. Each item has
exactly the string keys `value` and `variable`. `variable` is the local's bare
name. `value` is the Python `repr()` string of the value at the observation
point, not `str()` and not a JSON rendering. For a container, use `repr()` of
the whole container, preserving its runtime iteration/insertion order; thus
strings retain quotes, `None` and `True`/`False` use Python spellings, and an
embedded newline is a real newline character within the JSON string. No
requested variable is expected to be absent; do not substitute an empty
string, JSON `null`, or an omitted item."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_changed_locals(line: str) -> dict[str, str]:
    marker = " locals="
    if marker not in line:
        fail(f"Target event has no locals payload: {line.rstrip()}")
    payload = line.rsplit(marker, 1)[1].strip()
    try:
        parsed = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:
        fail(f"Could not parse locals payload: {payload!r} ({exc})")
    if not isinstance(parsed, dict):
        fail(f"Locals payload is not a dictionary: {payload!r}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
        fail(f"Locals payload has unexpected key/value types: {payload!r}")
    return parsed


def harvest(trace_path: Path) -> dict[str, object]:
    if not trace_path.is_file():
        fail(f"Trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"Trace log is empty: {trace_path}")

    target_events = 0
    occurrence = 0
    state: dict[str, str] | None = None
    previous_line: int | None = None
    captured: dict[str, str] | None = None

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match or match.group("func") != TARGET_FUNC:
                continue
            if TARGET_FILE not in match.group("file").replace("\\", "/"):
                continue

            target_events += 1
            event = match.group("event")
            line_number = int(match.group("line"))
            changed = parse_changed_locals(raw_line)

            if event == "call":
                state = {}
                previous_line = None
            if state is None:
                fail("Encountered a target event before its call event")
            state.update(changed)

            if event == "line":
                if (
                    line_number == OBSERVATION_EVENT_LINE
                    and previous_line == PRECEDING_LINE
                ):
                    occurrence += 1
                    if occurrence == OBSERVATION_OCCURRENCE:
                        missing = sorted(set(VARIABLES) - set(state))
                        if missing:
                            fail(
                                "Requested locals missing at observation point: "
                                + ", ".join(missing)
                            )
                        captured = {variable: state[variable] for variable in VARIABLES}
                previous_line = line_number

            if event == "return":
                state = None
                previous_line = None

    if target_events == 0:
        fail(
            f"Trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if occurrence < OBSERVATION_OCCURRENCE:
        fail(
            f"Found only {occurrence} executions of line {PRECEDING_LINE}; "
            f"need {OBSERVATION_OCCURRENCE}"
        )
    if captured is None:
        fail("The requested observation state was not captured")

    observed_state = [
        {"value": captured[variable], "variable": variable}
        for variable in sorted(VARIABLES)
    ]
    return {"observed_state": observed_state}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle_answer = harvest(args.trace_log)
    document = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
