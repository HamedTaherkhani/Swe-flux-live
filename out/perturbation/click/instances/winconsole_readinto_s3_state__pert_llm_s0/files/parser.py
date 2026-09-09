from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/_winconsole.py"
TARGET_FUNC = "click._winconsole._WindowsConsoleReader.readinto"
OBSERVATION_LINE = 145
FOLLOWING_LINE = 152
EXECUTION_NUMBER = 23
VARIABLES = ("bytes_to_be_read", "code_units_read", "code_units_to_be_read", "rv")

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
    r".*? locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run exactly the pytest test
`click_qa/winconsole_readinto_s3_state/files/testcase.py::WindowsConsoleReaderStateTest::test_generated_read_schedule`.
Consider only the frame of
`click._winconsole._WindowsConsoleReader.readinto`, implemented in
`src/click/_winconsole.py`; activity in the test, its callback objects,
callers, and callees does not itself create an observation.

What are the values of the local variables `bytes_to_be_read`,
`code_units_read`, `code_units_to_be_read`, and `rv` immediately after
absolute line 145 of `src/click/_winconsole.py` has executed for the 23rd time
during this test run? Absolute line numbers are 1-based source line numbers in
that file as it exists in the repository. Count an execution when the
multi-line assignment beginning at line 145 has completed, and count those
completed executions 1-based in chronological order across the whole test.
An invocation is one call of exactly the target function, also counted
1-based in chronological order. In this test every invocation reaches line
145, so its 23rd execution occurs in the 23rd invocation.

Line 145 begins the multi-line assignment whose call expression ends on line
151. "Immediately after line 145 has executed" means after that complete
assignment has finished, including callback side effects, and before line 152
executes. Under Python line-event semantics, a line event observes locals
immediately before the statement or expression associated with that event
executes; a multi-line statement is associated here with line 145, where the
assignment begins. Evaluation of this particular multi-line call produces
line events for its argument lines and then another event at line 145; only
the occurrence of line 145 immediately followed by line 152 marks one
completed execution for this question. Thus inspect the target frame at line
152 and count those line-145-to-line-152 transitions. The `def` line,
decorators, and docstring lines are irrelevant unless Python executes a line
event there, and none changes this specified observation point.

Report each value as the exact Python `repr()` string of the named local at
the observation point. Apply `repr()` to each whole object, including a
ctypes scalar or a container, rather than converting its contents to JSON.
Consequently strings keep their Python quotes, bytes keep the `b` prefix, and
`None` and booleans use Python spellings (for example, `None`, not JSON
`null`). Backslash escapes produced by `repr()` remain backslash characters
in the decoded JSON string; if a repr contains a real embedded newline, JSON
escaping must decode back to that newline. A missing local is an error, never
JSON null, an empty string, or an omitted record.

Return exactly
`{"observed_state": [{"value": str, "variable": str}, ...]}` as
JSON-compatible data. Include exactly one record for each of the four named
variables. Sort records by `variable` in ascending Unicode-code-point
lexicographic order. Do not deduplicate records or equal values; the variable
name is the sole ordering key, so no tie-breaker is needed."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw: str, trace_line_number: int) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"cannot parse locals on trace line {trace_line_number}: {error}")
    if not isinstance(parsed, dict):
        fail(f"locals on trace line {trace_line_number} are not a dictionary")
    if not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in parsed.items()
    ):
        fail(f"locals on trace line {trace_line_number} have invalid entries")
    return parsed


def collect_observation(trace_text: str) -> tuple[dict[str, str], int, int]:
    current: dict[str, str] | None = None
    previous_line: int | None = None
    execution_count = 0
    target_events = 0
    target_line_events = 0
    observation: dict[str, str] | None = None

    for trace_line_number, raw_line in enumerate(trace_text.splitlines(), 1):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_locals(match.group("locals"), trace_line_number)

        if event == "call":
            if current is not None:
                fail("encountered a nested target invocation")
            current = dict(changed)
            previous_line = None
            continue

        if current is None:
            fail(f"encountered target {event} event outside an invocation")
        current.update(changed)

        if event == "line":
            target_line_events += 1
            line_number = int(match.group("line"))
            if (
                line_number == FOLLOWING_LINE
                and previous_line == OBSERVATION_LINE
            ):
                execution_count += 1
                if execution_count != EXECUTION_NUMBER:
                    previous_line = line_number
                    continue
                if observation is not None:
                    fail("encountered the requested observation more than once")
                missing = [name for name in VARIABLES if name not in current]
                if missing:
                    fail("missing requested locals: " + ", ".join(missing))
                observation = {name: current[name] for name in VARIABLES}
            previous_line = line_number
        elif event == "return":
            current = None
            previous_line = None

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_line_events == 0:
        fail(f"trace contains zero line events for target function {TARGET_FUNC}")
    if execution_count < EXECUTION_NUMBER:
        fail(
            f"line {OBSERVATION_LINE} executed only {execution_count} times; "
            f"need {EXECUTION_NUMBER}"
        )
    if observation is None:
        fail(
            f"did not observe line {FOLLOWING_LINE} immediately after the "
            f"{EXECUTION_NUMBER}rd execution of line {OBSERVATION_LINE}"
        )
    if current is not None:
        fail("trace ended before the final target invocation returned")
    return observation, target_events, target_line_events


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    observation, _target_events, _target_line_events = collect_observation(trace_text)
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
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
