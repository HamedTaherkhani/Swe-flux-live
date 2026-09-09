from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "scrapy.utils.request.fingerprint"
ASSIGNMENT_START_LINE = 89
TARGET_EVENT_RE = re.compile(
    r"scrapy/utils/request\.py:(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run only the pytest test
`scrapy_qa/request_fingerprint_s3_state/files/testcase.py::TestRequestFingerprintProgramState::test_accumulated_header_state`.
During that test run, consider the first invocation of
`scrapy.utils.request.fingerprint` in `scrapy/utils/request.py`. An invocation
means one call of that exact function, numbered from 1 in chronological order;
frames of comprehensions or any other functions are not invocations.

Report the complete chronological history of the local variable `headers`
immediately after each execution of the assignment statement that begins on
absolute, 1-based line 89 and ends on line 92 of that file, during invocation
1. For this multi-line statement, line 89 is the line where the statement
begins; one history step is added only after the whole assignment, including
its list comprehension, has completed. Step numbers are 1-based in assignment
completion order. Keep every sample, including duplicate values if any; do
not sort or deduplicate the samples.

Return exactly
`{"value_history": [{"step": <int>, "value": <str>}, ...]}`. Each `value` is
Python `repr(headers)` at that observation point, i.e. the `repr` of the whole
dictionary using its actual insertion order, not a separately sorted
rendering. Thus strings inside the dictionary retain quotes, bytes and
booleans would use Python spellings such as `b'x'` and `True`, and embedded
newlines, if present, are newline characters in the JSON string value. No
sample is represented by JSON null or by an omitted key. The only ordering is
the chronological step order described above; within each step object the
keys are exactly `step` and `value`."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    current_locals: dict[str, str] = {}
    waiting_for_assignment_completion = False
    history: list[dict[str, int | str]] = []

    for raw_line in text.splitlines():
        match = TARGET_EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse target locals on trace line: {raw_line!r}: {exc}")
        if not isinstance(changed_locals, dict):
            fail(f"target locals are not a dictionary: {changed_locals!r}")

        if event == "call":
            invocation += 1
            current_locals = {}
            waiting_for_assignment_completion = False

        current_locals.update(changed_locals)

        if invocation != 1:
            continue

        if (
            waiting_for_assignment_completion
            and event == "line"
            and line_number in {87, 93}
            and "headers" in changed_locals
        ):
            if "headers" not in current_locals:
                fail("headers is unavailable after the assignment completed")
            history.append(
                {"step": len(history) + 1, "value": current_locals["headers"]}
            )
            waiting_for_assignment_completion = False

        if event == "line" and line_number == ASSIGNMENT_START_LINE:
            waiting_for_assignment_completion = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")
    if waiting_for_assignment_completion:
        fail("trace ended before the final line-89 assignment completed")
    if len(history) < 15:
        fail(f"expected at least 15 assignment completions, found {len(history)}")

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "value_history": [{"step": "int", "value": "str"}]
        },
        "oracle_answer": {"value_history": history},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out_path} with {len(history)} history steps")


if __name__ == "__main__":
    main()
