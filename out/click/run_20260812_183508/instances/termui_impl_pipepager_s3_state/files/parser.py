from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FUNC = "click._termui_impl._pipepager"
TARGET_FILE_SUFFIX = "/src/click/_termui_impl.py"
OBSERVED_LINE = 572
OBSERVED_OCCURRENCE = 16
VARIABLES = ("color", "cmd_name", "cmd_params", "encoding", "env", "less_flags")

QUESTION = """Run the single pytest test `click_qa/termui_impl_pipepager_s3_state/files/testcase.py::TestPipePagerState::test_generated_pager_wait_state`. During that test run, consider `click._termui_impl._pipepager` in `src/click/_termui_impl.py`. What are the values of the local variables `color`, `cmd_name`, `cmd_params`, `encoding`, `env`, and `less_flags` immediately after line 572 (`c.wait()`) has executed for the 16th time during the test run?

Line numbers are absolute, 1-based physical lines in the named repository file. Count an execution of line 572 each time the statement on that line is attempted, including an attempt that raises an exception; occurrences are numbered from 1 in chronological order across the whole test run. The observation point is after the 16th attempt has completed normally and before the next statement executes. For a multi-line statement, its line is the physical line where the statement or expression begins; decorator, `def`, and docstring lines are irrelevant because only executions of line 572 are counted.

Return exactly `{"observed_state": [{"value": "str", "variable": "str"}]}`. The `observed_state` JSON array must contain exactly one object for each named variable, ordered by the variable name in ascending Unicode code-point order, with no deduplication. In each object, `variable` is the local variable's bare name and `value` is a JSON string containing Python's `repr()` of that variable at the observation point. For a container, use `repr()` of the whole container and preserve the container's own iteration/insertion order; do not sort or separately serialize its contents. Thus strings retain Python quotes and escapes, and `None` and booleans use Python spellings; for example, the tuple whose items are the string `sample` and no value is represented by the JSON string whose decoded contents are `('sample', None)`. JSON escaping is only the encoding of that repr string, including any embedded newline characters; it does not change the decoded value. No named variable is absent at this observation point, so do not use JSON null, an empty substitute, or omit an entry."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    line_occurrences = 0
    current_locals: dict[str, str] = {}
    observed: dict[str, str] | None = None

    event_pattern = re.compile(
        r"^(?P<prefix>.*) "
        r"(?P<file>\S+):(?P<line>\d+) "
        + re.escape(TARGET_FUNC)
        + r" event=(?P<event>\w+)(?P<middle>.*?) locals=(?P<locals>\{.*\})$"
    )

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
            continue

        target_events += 1
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as error:
            fail(f"cannot parse locals from target trace event: {error}")
        if not isinstance(changed_locals, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed_locals.items()
        ):
            fail("target trace event has malformed locals")
        current_locals.update(changed_locals)

        event = match.group("event")
        line_number = int(match.group("line"))
        if event == "line" and line_number == OBSERVED_LINE:
            line_occurrences += 1
            continue

        if (
            line_occurrences == OBSERVED_OCCURRENCE
            and event == "line"
            and line_number == 576
        ):
            missing = [name for name in VARIABLES if name not in current_locals]
            if missing:
                fail(f"observation is missing locals: {', '.join(missing)}")
            observed = {name: current_locals[name] for name in VARIABLES}
            break

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if line_occurrences < OBSERVED_OCCURRENCE:
        fail(
            f"line {OBSERVED_LINE} executed only {line_occurrences} times; "
            f"expected at least {OBSERVED_OCCURRENCE}"
        )
    if observed is None:
        fail("did not find the precise post-line-572 observation point")

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

    oracle_answer = parse_trace(arguments.trace_log)
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
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
