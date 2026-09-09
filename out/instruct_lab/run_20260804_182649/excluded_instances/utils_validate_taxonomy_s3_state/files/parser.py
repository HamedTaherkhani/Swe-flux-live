#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/utils.py"
TARGET_FUNC = "instructlab.utils.validate_taxonomy"
OBSERVATION_LINE = 458
OBSERVATION_OCCURRENCE = 18
VARIABLES = ("errors", "total_errors", "total_warnings", "warnings")
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b.*? locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_changed_locals(text: str, trace_line: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals on trace line {trace_line}: {exc}")
    if not isinstance(value, dict):
        fail(f"locals on trace line {trace_line} are not a dictionary")
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        fail(f"locals on trace line {trace_line} do not map strings to repr strings")
    return value


def observed_state(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    occurrence_count = 0
    frame_state: dict[str, str] = {}
    selected: dict[str, str] | None = None

    for trace_line, raw_line in enumerate(text.splitlines(), start=1):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_changed_locals(match.group("locals"), trace_line)

        if event == "call":
            frame_state = {}
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            occurrence_count += 1
            if occurrence_count == OBSERVATION_OCCURRENCE:
                missing = [name for name in VARIABLES if name not in frame_state]
                if missing:
                    fail(
                        "observation is missing requested local(s): "
                        + ", ".join(missing)
                    )
                selected = {name: frame_state[name] for name in VARIABLES}

        if event in {"return", "exception"}:
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if occurrence_count < OBSERVATION_OCCURRENCE:
        fail(
            f"expected at least {OBSERVATION_OCCURRENCE} executions of line "
            f"{OBSERVATION_LINE}; found {occurrence_count}"
        )
    if selected is None:
        fail("the requested observation point was not captured")

    return [
        {"value": selected[variable], "variable": variable}
        for variable in sorted(VARIABLES)
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = observed_state(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/utils_validate_taxonomy_s3_state/files/testcase.py::"
        "TestTaxonomyState::test_generated_directory_via_cli` against this "
        "repository. In `instructlab.utils.validate_taxonomy` in "
        "`src/instructlab/utils.py`, what are the concrete values of the local "
        "variables `errors`, `total_errors`, `total_warnings`, and `warnings` "
        "immediately after absolute physical line 457 has executed for the 18th "
        "time during the test run? Line numbers are 1-based physical line numbers "
        "in the named file as it exists for this test. Line 457 is the single-line "
        "augmented assignment `total_warnings += warnings`: it first reads both "
        "operands and then writes the sum to `total_warnings`, and the requested "
        "state is after that write is complete but before line 458 executes. Count "
        "an execution only in an active frame of exactly the named function; "
        "executions in callers, callees, comprehensions, and other functions do not "
        "count. Count these executions chronologically and 1-based across the whole "
        "test run, retaining every execution and performing no deduplication. An "
        "invocation means one runtime call of exactly the named function, counted "
        "chronologically and 1-based, although the requested point is selected by "
        "line-execution count across all invocations rather than by invocation "
        "number. Report every value as the exact Python `repr()` string of the whole "
        "local value at that moment, with no truncation or normalization. For a "
        "container, use Python `repr()` of the whole container rather than "
        "recursively converting it to JSON; strings retain their Python quotes, "
        "`None` and `True` use Python spellings, and a hypothetical list could be "
        "represented by the JSON string \"[6, 'example']\". Embedded newline "
        "characters in a repr are included as real characters and escaped only as "
        "required by JSON encoding. Every requested variable is present; no absent "
        "key, empty-string sentinel, or JSON `null` is used for a missing value. "
        "Return exactly one JSON object with the key `observed_state`. Its value is "
        "a JSON array containing one entry per requested variable, sorted by bare "
        "variable name in ascending Unicode code-point order; there are no ties and "
        "entries are not deduplicated. Each entry has exactly the keys `value` and "
        "`variable` in that order, and both values are JSON strings. The `variable` "
        "value is the bare local-variable name, and `value` is its Python repr string "
        "as defined above."
    )
    payload = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": answer},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
