import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/utils/curl.py"
TARGET_FUNC = "scrapy.utils.curl.curl_to_request_kwargs"
ASSIGNMENT_LINE = 141
FOLLOWING_LINE = 143
OBSERVATION_NUMBER = 11
VARIABLES = ("argv", "cookies", "headers", "method", "result", "url")

QUESTION = """Run only the pytest test `scrapy_qa/curl_curl_to_request_kwargs_s3_state/files/testcase.py::CurlProgramStateTest::test_generated_curl_commands`. During that sole test method, consider `scrapy.utils.curl.curl_to_request_kwargs` in the repository-relative file `scrapy/utils/curl.py`. What are the values of the local variables `argv`, `cookies`, `headers`, `method`, `result`, and `url` immediately after absolute source line 141 has executed for the 11th time across all invocations of the target function during the test run?

Line numbers are absolute, 1-based line numbers in that file as it exists in the repository. Count executions of line 141 chronologically from 1 across the complete execution of the named test method, without deduplication. An invocation means one `call` of the target function during the test run and invocations are numbered chronologically from 1, although the requested ordinal counts executions of line 141 rather than invocations. A line execution means Python executes the statement or expression beginning on that line; for a multi-line statement, execution is attributed to the line where that statement or expression begins. The function's `def` line, decorator lines, and non-executed docstring lines do not count. “Immediately after” means after the assignment statement beginning on line 141 has completed and before the return statement beginning on line 143 executes.

Return a JSON object with exactly the key `observed_state`. Its value must be a list of exactly six objects, each with exactly the keys `value` and `variable`. Order these objects by `variable` in ascending lexicographic order, retain each named variable exactly once, and perform no deduplication. Each `variable` is the local variable name exactly as listed above. Each `value` is a JSON string containing Python `repr()` of that local's complete value at the observation point, with no normalization or truncation. For containers, use Python `repr()` of the whole container, so nested strings retain their quotes and Python spellings such as `None` and `True` are used; for example, a tuple containing a short string and no value has decoded JSON-string contents `('demo', None)`. Embedded newlines, if any, are real newline characters in the decoded JSON string. All six locals exist at this point; do not use JSON null, an empty string, or an omitted object to represent a missing local."""

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
                    "line 141 was not followed by the expected line 143 event "
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
