import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/downloadermiddlewares/retry.py"
TARGET_FUNC = "scrapy.downloadermiddlewares.retry.get_retry_request"
ASSIGNMENT_LINE = 130
FOLLOWING_LINE = 131
OBSERVATION_NUMBER = 19
VARIABLES = (
    "give_up_log_level",
    "level",
    "max_retry_times",
    "priority_adjust",
    "reason",
    "retry_times",
)

QUESTION = """Run only the pytest test `scrapy_qa/retry_get_retry_request_s3_state/files/testcase.py::RetryProgramStateTest::test_generated_response_retries`. During that test run, consider `scrapy.downloadermiddlewares.retry.get_retry_request` in the repository-relative file `scrapy/downloadermiddlewares/retry.py`. What are the values of the local variables `give_up_log_level`, `level`, `max_retry_times`, `priority_adjust`, `reason`, and `retry_times` immediately after absolute source line 130 has executed for the 19th time across all invocations of that function?

Line numbers are absolute, 1-based line numbers in that file as it exists in the repository. Count executions of line 130 chronologically from 1 over the complete execution of the sole named test method. An invocation means one call of the target function and invocations are numbered chronologically from 1, although the requested ordinal counts executions of line 130 rather than invocations. A line execution occurs when Python executes the statement or expression beginning on that line; for a multi-line statement it is attributed to the line where the statement or expression begins. The function's `def` line, decorators, and unexecuted docstring lines do not count. “Immediately after” means after the assignment on line 130 has completed and before the statement beginning on line 131 executes.

Return a JSON object with exactly the key `observed_state`. Its value must be a list of exactly six objects, each with exactly the keys `value` and `variable`. Order the objects by `variable` in ascending lexicographic order, retain every listed variable once, and perform no deduplication. Each `variable` is the local variable name exactly as written above. Each `value` is a JSON string containing Python `repr()` of that local's complete value at the observation point, with no normalization or truncation. Containers use the `repr()` of the whole container, so strings retain quotes and Python spellings such as `None` and `True` are used; for example, the value of a list containing a short string and no value would be represented by the JSON string whose decoded contents are `['sample', None]`. Embedded newlines, if any, are newline characters in the decoded JSON string. All six locals must exist at this point: do not substitute JSON null, an empty string, or an omitted entry for a missing local."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    observation_count = 0
    current_state: dict[str, str] | None = None
    awaiting_post_assignment = False
    observed: dict[str, str] | None = None

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse locals for target event: {exc}")
        if not isinstance(changed, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed.items()
        ):
            fail("target event locals are not a string-to-string dictionary")

        if event == "call":
            current_state = {}
            awaiting_post_assignment = False
        if current_state is None:
            fail("encountered a target event before its call event")
        current_state.update(changed)

        if awaiting_post_assignment:
            if event != "line" or line_number != FOLLOWING_LINE:
                fail(
                    "line 130 was not followed by the expected line 131 event "
                    "in the same target invocation"
                )
            observation_count += 1
            if observation_count == OBSERVATION_NUMBER:
                missing = [name for name in VARIABLES if name not in current_state]
                if missing:
                    fail(f"missing locals at observation point: {missing}")
                observed = {name: current_state[name] for name in VARIABLES}
            awaiting_post_assignment = False

        if event == "line" and line_number == ASSIGNMENT_LINE:
            awaiting_post_assignment = True
        elif event in {"return", "exception"}:
            current_state = None
            awaiting_post_assignment = False

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if observed is None:
        fail(
            f"trace contains only {observation_count} completed executions of "
            f"line {ASSIGNMENT_LINE}; need {OBSERVATION_NUMBER}"
        )

    return {
        "observed_state": [
            {"value": observed[name], "variable": name} for name in sorted(VARIABLES)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle_answer = parse_trace(args.trace_log)
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
