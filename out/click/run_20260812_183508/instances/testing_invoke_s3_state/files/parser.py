#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "click.testing.CliRunner.invoke"
OBSERVATION_LINE = 728
FOLLOWING_LINE = 666
INVOCATION_NUMBER = 4
VARIABLES = ("output", "return_value", "stderr", "stdout")

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r".*? locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run exactly the pytest test
`click_qa/testing_invoke_s3_state/files/testcase.py::TestInvokeProgramState::test_seeded_multi_path_invocations`.
Consider calls of `click.testing.CliRunner.invoke` whose implementation is in
`src/click/testing.py`, and only that function's own frame; activity in the
test, the invoked commands, callers, callees, context managers, and nested
functions does not itself create an observation.

What are the values of the local variables `output`, `return_value`, `stderr`,
and `stdout` immediately after absolute line 728 of `src/click/testing.py` has
executed for the fourth time during this test run? Line numbers are absolute,
1-based source line numbers in that file as it exists in the repository. An
invocation is one call of exactly `click.testing.CliRunner.invoke`, counted
1-based in chronological order. In this test, the fourth execution of line
728 occurs in the fourth invocation. "Immediately after line 728" means after
the assignment beginning on that line has completed and before the next
source line in the target frame executes.

For line-event semantics, an event observes locals immediately before the
statement or expression at that line executes. A multi-line statement or
expression is associated with the absolute line on which its executed
statement or expression begins. Thus the observation can be obtained from the
target frame at the next executed target line after line 728. The function
`def` line, decorators, and docstring lines do not count unless Python
actually executes a line event there; they do not affect the specified point.

Report each value as the exact Python `repr()` string of that local at the
observation point. For a container, use `repr()` of the whole container, not
element-wise JSON conversion; strings retain Python quotes, bytes retain the
`b` prefix, and `None` and booleans use Python spellings. Backslash escapes
created by `repr()` remain backslash characters in the decoded JSON string.
If a repr string itself contains an embedded real newline, JSON escaping
preserves that newline in the decoded string. A missing value must cause an
error; it is never represented by JSON null, an empty string, or an omitted
record.

Return exactly
`{"observed_state": [{"value": str, "variable": str}, ...]}` as
JSON-compatible data. Include exactly one record for each of the four named
variables, sorted by `variable` in ascending Unicode-code-point
lexicographic order. Do not remove records or values as duplicates; variable
name is the sole ordering key, so no tie-breaker is needed."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw: str, trace_line_number: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"could not parse locals on trace line {trace_line_number}: {error}")
    if not isinstance(value, dict):
        fail(f"locals payload on trace line {trace_line_number} is not a dict")
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        fail(f"locals payload on trace line {trace_line_number} has invalid entries")
    return value


def collect_observation(trace_text: str) -> tuple[dict[str, str], int, int]:
    invocation_count = 0
    line_event_count = 0
    current: dict[str, str] | None = None
    current_invocation = 0
    previous_line: int | None = None
    observation: dict[str, str] | None = None

    for trace_line_number, raw_line in enumerate(trace_text.splitlines(), 1):
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        event = match.group("event")
        changed = parse_locals(match.group("locals"), trace_line_number)

        if event == "call":
            if current is not None:
                fail("encountered a nested target invocation")
            invocation_count += 1
            current_invocation = invocation_count
            current = dict(changed)
            previous_line = None
            continue

        if current is None:
            fail(f"encountered target {event} event outside an invocation")
        current.update(changed)

        if event == "line":
            line_event_count += 1
            line_number = int(match.group("line"))
            if (
                current_invocation == INVOCATION_NUMBER
                and line_number == FOLLOWING_LINE
                and previous_line == OBSERVATION_LINE
            ):
                if observation is not None:
                    fail("encountered the requested observation more than once")
                missing = [name for name in VARIABLES if name not in current]
                if missing:
                    fail(
                        "requested locals are missing at the observation: "
                        + ", ".join(missing)
                    )
                observation = {name: current[name] for name in VARIABLES}
            previous_line = line_number
        elif event == "return":
            current = None
            current_invocation = 0
            previous_line = None

    if current is not None:
        fail("trace ended before the final target invocation returned")
    if observation is None:
        fail(
            "did not find line 666 immediately following line 728 "
            "in the fourth target invocation"
        )
    return observation, invocation_count, line_event_count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    observation, invocation_count, line_event_count = collect_observation(trace_text)
    if invocation_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < INVOCATION_NUMBER:
        fail(
            f"trace has only {invocation_count} target invocations; "
            f"expected at least {INVOCATION_NUMBER}"
        )
    if line_event_count == 0:
        fail(f"trace contains zero line events for {TARGET_FUNC}")

    observed_state = [
        {"value": observation[name], "variable": name} for name in sorted(VARIABLES)
    ]
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": observed_state},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
