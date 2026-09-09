#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "scripts.topic_repos.main"
LOOP_HEADER_LINE = 35
LOOP_BODY_FIRST_LINE = 36
REQUESTED_ITERATION = 73

QUESTION = """Run only the pytest test `fastapi_qa/topic_repos_main_s2_loops/files/testcase.py::TestGeneratedTopicRepositories::test_seeded_repository_catalog`. During that test run, consider the first invocation of the exact function `scripts.topic_repos.main` in `scripts/topic_repos.py`.

For the `for` loop whose header is on line 35, what is the value of the loop variable `repo` at iteration 73? An invocation is one Python `call` of this exact function, counted 1-based in chronological order; only invocation 1 is requested. Iterations are also counted 1-based in chronological order, and iteration N means the Nth execution of the loop body's first line, line 36 (`if repo.full_name == settings.github_repository:`), in that same invocation's frame. Executions in callees or other function frames do not count. Do not sort or deduplicate iterations.

Report `value` as the full, untruncated Python `repr(repo)` evaluated immediately before line 36 executes on the requested iteration. This is the `repr()` of the whole object, including Python punctuation and quoting; for example, an unrelated object could be represented as `Widget(name='demo')`. Store those exact representation characters as a JSON string (with only the escaping required by JSON), rather than using `str()`, JSON object notation, or JSON `null`. The variable name is the raw string `repo`.

Line numbers are absolute, 1-based line numbers in the named repository file as it exists for the test. Both the loop header and its first body statement begin on the stated single lines; the `def` line, decorators, docstrings, and events for continuation lines of multi-line statements are irrelevant and do not count.

Return `oracle_answer` with exactly the shape `{"nth_iteration": 73, "value": <string>, "variable": "repo"}`. `nth_iteration` is a JSON integer, while `value` and `variable` are JSON strings. The object has exactly these three fixed keys; because each requested field is a scalar for one fixed iteration, no output sorting, tie-breaking, duplicate removal, missing-value, empty-value, or null convention applies."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*scripts/topic_repos\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)(?P<details>.*)$"
)
LOCALS_RE = re.compile(r"(?:^| )locals=(?P<locals>\{.*\})$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(details: str, line_number: int) -> dict:
    match = LOCALS_RE.search(details)
    if match is None:
        fail(f"line-{line_number} event has no parseable locals mapping")
    try:
        parsed = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse locals for line {line_number}: {exc}")
    if not isinstance(parsed, dict):
        fail(f"locals for line {line_number} are not a dictionary")
    return parsed


def harvest(trace_path: Path) -> dict:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    first_invocation_active = False
    first_invocation_finished = False
    iteration = 0
    requested_value = None

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            target_calls += 1
            if target_calls == 1:
                if first_invocation_active or first_invocation_finished:
                    fail("invalid first-invocation state at target call event")
                first_invocation_active = True

        if (
            first_invocation_active
            and event == "line"
            and line_number == LOOP_BODY_FIRST_LINE
        ):
            iteration += 1
            if iteration == REQUESTED_ITERATION:
                event_locals = parse_locals(match.group("details"), line_number)
                if "repo" not in event_locals:
                    fail("requested iteration does not record the loop variable 'repo'")
                value = event_locals["repo"]
                if not isinstance(value, str):
                    fail("recorded repr for loop variable 'repo' is not a string")
                requested_value = value

        if first_invocation_active and event == "return":
            first_invocation_active = False
            first_invocation_finished = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if not first_invocation_finished:
        fail("the first target invocation did not produce a return event")
    if iteration < REQUESTED_ITERATION:
        fail(
            f"line-{LOOP_HEADER_LINE} loop produced only {iteration} iterations; "
            f"iteration {REQUESTED_ITERATION} does not exist"
        )
    if requested_value is None:
        fail("the requested loop-variable value was not harvested")

    return {
        "nth_iteration": REQUESTED_ITERATION,
        "value": requested_value,
        "variable": "repo",
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {
            "nth_iteration": "int",
            "value": "str",
            "variable": "str",
        },
        "oracle_answer": harvest(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    arguments.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
