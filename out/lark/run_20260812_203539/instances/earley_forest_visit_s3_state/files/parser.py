import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "lark.parsers.earley_forest.ForestVisitor.visit"
TARGET_FILE = "lark/parsers/earley_forest.py"
OBSERVED_LINE = 330
FOLLOWING_LINE = 331

QUESTION = """Run only the pytest test `lark_qa/earley_forest_visit_s3_state/files/testcase.py::TestGeneratedEarleyForestState::test_generated_ambiguous_sequence`. During that test run, consider the first invocation of `lark.parsers.earley_forest.ForestVisitor.visit` in `lark/parsers/earley_forest.py`. An invocation means one call of that function, numbered from 1 in chronological call order.

Report the complete ordered history of the local variable `current` immediately after line 330 (`current_id = id(current)`) has executed on every occasion in that first invocation. Line numbers are absolute, 1-based line numbers in the named repository file. Here, “immediately after” means after the statement on line 330 has completed and before the statement on line 331 begins. Step 1 is the first such execution, step 2 the second, and so on. Include every execution in chronological order and retain duplicate values; do not sort or deduplicate observations.

Return exactly one JSON object with the shape `{"value_history": [{"step": <integer>, "value": <string>}, ...]}`. `step` is the 1-based observation number. Each `value` is the Python `repr()` string of the whole value of `current` at that observation point, without normalization or truncation. If a reported value is a container, use the `repr()` of the whole container rather than separately formatting its elements: strings therefore keep their quotes, and `None` and booleans use Python spellings such as `None` and `True`. If a repr contains a newline, it is represented by an actual newline character in the decoded JSON string (escaped as required by JSON syntax)."""


EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.*):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>\w+).*?\slocals=(?P<locals>\{.*\})$"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line, line_number):
    match = EVENT_RE.match(raw_line.rstrip("\n"))
    if not match:
        return None
    try:
        changed_locals = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse locals on trace line {line_number}: {exc}")
    if not isinstance(changed_locals, dict):
        fail(f"locals on trace line {line_number} are not a dictionary")
    return {
        "file": match.group("file").replace("\\", "/"),
        "line": int(match.group("line")),
        "func": match.group("func"),
        "event": match.group("event"),
        "locals": changed_locals,
    }


def build_answer(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_count = 0
    in_first_invocation = False
    state = {}
    previous_line = None
    values = []

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for line_number, raw_line in enumerate(trace_file, start=1):
            event = parse_event(raw_line, line_number)
            if event is None:
                continue
            if event["func"] != TARGET_FUNC or not event["file"].endswith(TARGET_FILE):
                continue

            target_events += 1
            if event["event"] == "call":
                invocation_count += 1
                in_first_invocation = invocation_count == 1
                if in_first_invocation:
                    state = {}
                    previous_line = None

            if not in_first_invocation:
                continue

            state.update(event["locals"])
            if (
                event["event"] == "line"
                and event["line"] == FOLLOWING_LINE
                and previous_line == OBSERVED_LINE
            ):
                if "current" not in state:
                    fail(
                        f"`current` is unavailable after line {OBSERVED_LINE} "
                        f"at trace line {line_number}"
                    )
                values.append(state["current"])

            if event["event"] == "line":
                previous_line = event["line"]
            if event["event"] == "return":
                in_first_invocation = False

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")
    if not values:
        fail(
            f"first invocation contains no observations immediately after "
            f"line {OBSERVED_LINE}"
        )

    return {
        "value_history": [
            {"step": step, "value": value}
            for step, value in enumerate(values, start=1)
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = build_answer(Path(args.trace_log))
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "value_history": [{"step": "int", "value": "str"}]
        },
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {output_path}")


if __name__ == "__main__":
    main()
