import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.anonymize.anonymize"
TARGET_LINE = 93
TARGET_OCCURRENCE = 27
VARIABLES = ("alias", "counter", "i", "is_number", "key")
EVENT_RE = re.compile(
    r" (?P<file>/\S*sqlglot/anonymize\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run only the pytest test `sqlglot_qa/anonymize_anonymize_s3_state/files/testcase.py::TestAnonymizeProgramState::test_generated_mixed_query`. During that run, consider the first and only invocation of `sqlglot.anonymize.anonymize` in `sqlglot/anonymize.py`. An invocation means one entry into that function and is numbered 1-based in chronological order.

Observe the target function's own local frame immediately after the assignment statement on absolute, 1-based line 93 (`alias = seen.get(key)`) has completed for the 27th time in that invocation. Count only completed executions of that exact source line, 1-based in chronological order; executions of other lines, the `def` line, docstring lines, and calls in helper functions do not count. Line numbers refer to the named repository file as it exists for this test. For a multi-line statement, execution is attributed to the line on which the statement or expression begins, although line 93 here is a single-line statement.

Report the local variables `alias`, `counter`, `i`, `is_number`, and `key` at that one observation point. Return exactly `{"observed_state": [{"value": "...", "variable": "..."}]}`, where `observed_state` is a JSON list containing exactly one record for each named variable. Sort records by `variable` in ascending Unicode code-point order; do not deduplicate records. Each `variable` is the local's bare name. Each `value` is Python `repr()` of that local value, stored as a JSON string. For a container, use `repr()` of the whole container rather than recursively converting it; thus strings retain quotes and Python spellings such as `None` and `True` remain inside the value string (for example, the tuple `("demo", None)` would be represented by the value string `('demo', None)`). If a represented value contains an embedded newline, preserve that newline as part of the JSON string. All five locals exist at the observation point, so no missing-value or JSON-null convention is needed."""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")

    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    state = {}
    target_events = 0
    call_count = 0
    line_occurrences = 0
    capture_next_event = False
    observed = None

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            call_count += 1

        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"could not parse locals from target event: {exc}")
        if not isinstance(changed_locals, dict):
            fail("target event locals are not a dictionary")

        state.update(changed_locals)

        if capture_next_event:
            missing = [variable for variable in VARIABLES if variable not in state]
            if missing:
                fail(f"observation is missing locals: {', '.join(missing)}")
            observed = [
                {"value": state[variable], "variable": variable} for variable in VARIABLES
            ]
            break

        if event == "line" and line == TARGET_LINE:
            line_occurrences += 1
            if line_occurrences == TARGET_OCCURRENCE:
                capture_next_event = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if call_count != 1:
        fail(f"expected exactly one target invocation, found {call_count}")
    if observed is None:
        fail(
            f"line {TARGET_LINE} did not complete at least "
            f"{TARGET_OCCURRENCE} times in the target invocation"
        )

    result = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": observed},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
