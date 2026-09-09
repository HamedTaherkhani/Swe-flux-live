#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/cli/config/init.py"
TARGET_FUNC = "instructlab.cli.config.init.init"
OBSERVATION_LINES = {137, 146}
OBSERVED_VARIABLE = "cfg"
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

        if event == "line" and int(match.group("line")) in OBSERVATION_LINES:
            if OBSERVED_VARIABLE not in frame_state:
                fail(
                    f"{OBSERVED_VARIABLE!r} is absent at observation on trace "
                    f"line {trace_line}"
                )
            observations.append(frame_state[OBSERVED_VARIABLE])

        if event == "return":
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if not observations:
        fail(
            f"lines {sorted(OBSERVATION_LINES)} were never observed in an active "
            f"{TARGET_FUNC} frame"
        )
    if len(observations) != target_calls * len(OBSERVATION_LINES):
        fail(
            f"expected two observations for each of {target_calls} calls; "
            f"found {len(observations)}"
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
        "`instruct_lab_qa/init_init_m3_state/files/testcase.py::"
        "TestConfigStateTransitions::test_seeded_public_cli_profiles` against this "
        "repository. Across the entire test run, consider every invocation of "
        "exactly `instructlab.cli.config.init.init` in "
        "`src/instructlab/cli/config/init.py`. An invocation means one runtime "
        "call of exactly that function, numbered 1-based in chronological order; "
        "calls of decorators, callees, comprehensions, and other functions are not "
        "invocations. For every invocation, observe the local variable `cfg` at "
        "each executed-line event for physical lines 137 and 146, immediately "
        "before the statement beginning on that line executes. Thus the line-137 "
        "observation precedes `cfg = new_cfg`, while the line-146 observation "
        "follows the in-place attribute updates on lines 140 through 145 and "
        "precedes the `write_config` call. Include both observations from every "
        "invocation before deduplication. Line numbers are absolute, 1-based "
        "physical lines in the named file as it exists for this test. For a "
        "multi-line statement, an executed-line event belongs to the physical line "
        "where that statement or expression begins. The function's `def` line is "
        "call entry, not an observation; decorator and docstring lines are not "
        "observation points. Represent each observed value using exact Python "
        "`repr()` of the whole object at that point, including nested containers, "
        "with no truncation or normalization. Python spellings and quoting are "
        "retained inside each JSON string: for example, a hypothetical string "
        "value would be represented as the JSON string \"'sample'\", and values "
        "inside a container would use Python spellings such as `None` and `True`, "
        "not JSON `null` and `true`. Deduplicate equal repr strings across both "
        "program points and all invocations, then sort the distinct strings in "
        "ascending lexicographic order by Unicode code point, exactly as Python "
        "`sorted()` does. Deduplication removes all ties, so no secondary "
        "tie-breaker applies. Return exactly one JSON object with the single key "
        "`unique_values`; its value is a JSON array of JSON strings in that order, "
        "where each string is the Python repr just defined. There is no null, empty-"
        "string, or absent-value sentinel."
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
