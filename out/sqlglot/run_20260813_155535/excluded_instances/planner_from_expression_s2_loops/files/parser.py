import argparse
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.planner.Step.from_expression"
LOOP_BODY_LINE = 193
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/planner\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the single pytest test "
    "`sqlglot_qa/planner_from_expression_s2_loops/files/testcase.py::"
    "TestPlannerLoopBehavior::test_generated_aggregate_plan`. During that run, consider "
    "invocations of `sqlglot.planner.Step.from_expression` in "
    "`sqlglot/planner.py`. An invocation means one Python call of exactly that function "
    "(not a call of a nested local function), numbered 1-based in chronological call "
    "order. In invocation 1, how many iterations does the `for node in "
    "projection.walk():` loop whose header begins at absolute, 1-based source line 192 "
    "perform? Count an iteration each time the loop body's first statement, beginning at "
    "line 193, executes in that invocation's own frame. If the function recursively calls "
    "itself, each recursive call is a later invocation and its executions are excluded "
    "from invocation 1. Line numbers refer to the named file as it exists in the "
    "repository; for a multi-line statement, execution belongs to the line where the "
    "statement or expression begins. Return exactly a JSON object with the single key "
    "`loop_iteration_count` and an integer value. There is no sorting or deduplication: "
    "every qualifying execution is counted."
)


def compute_iteration_count(trace_path: Path) -> int:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_event_count = 0
    invocation_number = 0
    active_invocations: list[dict[str, int]] = []
    first_invocation_count = None

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_event_count += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            invocation_number += 1
            active_invocations.append({"number": invocation_number, "count": 0})
        elif event == "line" and line == LOOP_BODY_LINE:
            if not active_invocations:
                raise RuntimeError("target line event occurred outside an active invocation")
            active_invocations[-1]["count"] += 1
        elif event == "return":
            if not active_invocations:
                raise RuntimeError("target return occurred outside an active invocation")
            completed = active_invocations.pop()
            if completed["number"] == 1:
                first_invocation_count = completed["count"]

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if first_invocation_count is None:
        raise RuntimeError("the first target invocation did not complete")
    if first_invocation_count == 0:
        raise RuntimeError("the selected loop executed zero iterations")

    return first_invocation_count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {
            "loop_iteration_count": compute_iteration_count(args.trace_log),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
