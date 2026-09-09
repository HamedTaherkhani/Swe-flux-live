#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/clickext.py"
TARGET_FUNC = "instructlab.clickext.ConfigOption.get_help_record"
OBSERVATION_LINE = 193
OBSERVED_VARIABLE = "default_string"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b.*? locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_locals(text: str, trace_line: int) -> dict[str, str]:
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


def collect_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    observations: list[str] = []
    frame_state: dict[str, str] = {}

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
        changed = parse_locals(match.group("locals"), trace_line)
        if event == "call":
            target_calls += 1
            frame_state = {}
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            if OBSERVED_VARIABLE not in frame_state:
                fail(
                    f"{OBSERVED_VARIABLE!r} is absent at observation on trace "
                    f"line {trace_line}"
                )
            observations.append(frame_state[OBSERVED_VARIABLE])

        if event in {"return", "exception"}:
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if not observations:
        fail(
            f"line {OBSERVATION_LINE} was never observed in an active "
            f"{TARGET_FUNC} frame"
        )

    answer = sorted(set(observations))
    if len(answer) < 8:
        fail(f"expected at least 8 distinct observed values; found {len(answer)}")
    return answer


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    unique_values = collect_unique_values(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/clickext_get_help_record_m3_state/files/testcase.py::"
        "TestGeneratedTrainHelp::test_programmatic_train_help` against this "
        "repository. Across the entire run, consider every invocation of exactly "
        "`instructlab.clickext.ConfigOption.get_help_record` in "
        "`src/instructlab/clickext.py` that reaches physical line 193. An invocation "
        "means one runtime call of exactly that function, counted 1-based in "
        "chronological order; calls of other functions, including comprehension "
        "frames and callees, do not count. At each execution of line 193 by such a "
        "frame, observe the local variable `default_string` immediately before the "
        "multi-line assignment beginning there executes. This point is after exactly "
        "one of lines 185, 187, 189, or 191 has assigned `default_string`. Line "
        "numbers are absolute, 1-based physical lines in the named file as it exists "
        "for this test. For a multi-line statement, the relevant executed-line point "
        "is the line on which the statement or expression begins. The function's "
        "`def` line is associated with call entry rather than a line execution here; "
        "decorator and docstring lines are not observation points. Include every "
        "qualifying execution across all invocations before deduplication. Convert "
        "each observed value with exact Python `repr()` and perform no truncation or "
        "normalization. Thus a string value remains a repr string with Python quotes "
        "(for example, a hypothetical value could be represented by the JSON string "
        "\"'sample'\"); Python spellings such as `None` and `True` would be retained "
        "inside repr strings. Deduplicate equal repr strings, then sort the distinct "
        "strings in ascending lexicographic order by Unicode code point, exactly as "
        "Python `sorted()` does; deduplication removes all ties, so there is no "
        "secondary tie-breaker. Return exactly one JSON object with the single key "
        "`unique_values`. Its value is a JSON array of JSON strings in that order, "
        "where each string is the Python repr described above. No null or absent-value "
        "sentinel is used."
    )
    payload = {
        "question_kind": "M3_ProgramState",
        "question": question,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
