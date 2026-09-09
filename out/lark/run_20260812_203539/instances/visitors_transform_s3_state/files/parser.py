import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "lark.visitors.Transformer_NonRecursive.transform"
TARGET_FILE = "lark/visitors.py"
OBSERVED_LINE = 318
FOLLOWING_LINE = 319
OCCURRENCE = 17
VARIABLES = ("args", "res", "size", "stack")

QUESTION = """Run only the pytest test `lark_qa/visitors_transform_s3_state/files/testcase.py::TestNonRecursiveTransformState::test_seeded_variable_width_tree` (the sole test method in class `TestNonRecursiveTransformState`). During that test run, consider the first invocation of `lark.visitors.Transformer_NonRecursive.transform` in `lark/visitors.py`. An invocation means one `call` of that function, numbered from 1 in chronological call order.

Report the values of the local variables `args`, `res`, `size`, and `stack` immediately after line 318 (`res = self._call_userfunc(x, args)`) has executed for the 17th time in that first invocation. Count only completed executions of that specific line in the target frame; the first completed execution is occurrence 1. “Immediately after” means after the call and assignment on line 318 have completed and before the condition on line 319 begins. Line numbers are absolute, 1-based line numbers in the named repository file. Line 318 is a single-line statement, so its execution is attributed to the line on which that statement begins; the function's `def` line, comments, and blank lines do not count.

Return exactly one JSON object with the shape `{"observed_state": [{"value": <string>, "variable": <string>}, ...]}`. Include exactly four entries, ordered by `variable` in ascending lexicographic order: `args`, `res`, `size`, then `stack`; do not deduplicate entries. In each entry, `variable` is the local's bare name and `value` is the Python `repr()` string of that local's whole value at the observation point, with no normalization or truncation. For a container, use the `repr()` of the whole container rather than formatting elements separately. Thus strings keep their quotes, and `None` and booleans use Python spellings such as `None` and `True`, not JSON spellings. If a repr contains a newline, the decoded JSON string contains an actual newline character (escaped as required in the JSON text). All four locals exist at this observation point, so no missing-value or JSON `null` convention applies."""

EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.*):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>\w+).*?\slocals=(?P<locals>\{.*\})$"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line, trace_line_number):
    match = EVENT_RE.match(raw_line.rstrip("\n"))
    if not match:
        return None
    try:
        changed_locals = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse locals on trace line {trace_line_number}: {exc}")
    if not isinstance(changed_locals, dict):
        fail(f"locals on trace line {trace_line_number} are not a dictionary")
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
    completed_occurrences = 0
    observed = None

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for trace_line_number, raw_line in enumerate(trace_file, start=1):
            event = parse_event(raw_line, trace_line_number)
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
                completed_occurrences += 1
                if completed_occurrences == OCCURRENCE:
                    missing = [name for name in VARIABLES if name not in state]
                    if missing:
                        fail(
                            f"locals unavailable after occurrence {OCCURRENCE} "
                            f"of line {OBSERVED_LINE}: {missing}"
                        )
                    observed = [
                        {"value": state[name], "variable": name}
                        for name in VARIABLES
                    ]

            if event["event"] == "line":
                previous_line = event["line"]
            elif event["event"] == "return":
                in_first_invocation = False

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")
    if observed is None:
        fail(
            f"first invocation has only {completed_occurrences} completed "
            f"executions of line {OBSERVED_LINE}; need {OCCURRENCE}"
        )

    return {"observed_state": observed}


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": build_answer(Path(args.trace_log)),
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
