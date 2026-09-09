import argparse
import json
from pathlib import Path
import re


TARGET_FILE = "sqlglot/transforms.py"
TARGET_FUNC = (
    "sqlglot.transforms.explode_projection_to_unnest."
    "<locals>._explode_projection_to_unnest"
)
INVOCATION = 2
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/transforms\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run exactly the pytest node "
    "`sqlglot_qa/transforms_explode_projection_to_unnest_s1_cfg/files/testcase.py::"
    "TestExplodeProjectionControlFlow::test_seeded_projection_mix`. During that test, "
    "consider only the exact target function "
    "`sqlglot.transforms.explode_projection_to_unnest.<locals>."
    "_explode_projection_to_unnest` in `sqlglot/transforms.py`. An invocation means "
    "one Python `call` event for that exact function; number invocations 1-based in "
    "chronological call-event order for the complete test, and report the second "
    "invocation. What is the exact ordered sequence of executed source-line events in "
    "that invocation's own frame? Include only `line` events emitted after its `call` "
    "and before its matching `return`; exclude the `call`, `return`, and `exception` "
    "events themselves, all events in callees (including the nested `new_name` "
    "function), and all other invocations. Preserve chronological event order and "
    "preserve every repeated line event; do not sort or deduplicate. Line numbers are "
    "absolute, 1-based line numbers in the named repository file as it exists for the "
    "test run. The function's `def` line does not appear because it is represented by "
    "the excluded `call` event; decorator lines, docstrings, comments, and blank lines "
    "do not appear unless Python emits a `line` event for executable code there. For "
    "a multi-line statement, call, or condition, report the line where the currently "
    "executed statement or expression begins, even if its text continues on later "
    "lines. Components or nested expressions of a multi-line call that begin on "
    "continuation lines produce their own separate line events when Python reports "
    "them, so retain those events too. Return exactly one JSON object with the sole "
    "key `executed_path`, whose value is a JSON array in that preserved order. Each "
    "array element must be an object with exactly the keys `file`, `func`, and `line` "
    "in that order. In every element, `file` is the JSON string "
    "`sqlglot/transforms.py`, `func` is the fully dotted Python qualname JSON string "
    "`sqlglot.transforms.explode_projection_to_unnest.<locals>."
    "_explode_projection_to_unnest`, and `line` is the unquoted base-10 JSON integer "
    "for the event's line. There are no null or omitted values and no additional keys."
)


def compute_path(trace_path: Path) -> dict[str, list[dict[str, object]]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_event_count = 0
    invocation_count = 0
    selected_active = False
    selected_complete = False
    executed_path = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_event_count += 1
        event = match.group("event")

        if event == "call":
            invocation_count += 1
            if invocation_count == INVOCATION:
                if selected_active or selected_complete:
                    raise RuntimeError("selected invocation started more than once")
                selected_active = True
        elif event == "line" and selected_active:
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": int(match.group("line")),
                }
            )
        elif event == "return" and selected_active:
            selected_active = False
            selected_complete = True

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_count} target invocation(s), "
            f"not invocation {INVOCATION}"
        )
    if selected_active or not selected_complete:
        raise RuntimeError("selected target invocation did not complete")
    if not executed_path:
        raise RuntimeError("selected target invocation contains zero line events")
    if len(executed_path) < 50:
        raise RuntimeError("selected invocation contains fewer than 50 line events")
    if len({event["line"] for event in executed_path}) < 12:
        raise RuntimeError("selected invocation executes fewer than 12 distinct lines")

    return {"executed_path": executed_path}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": compute_path(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
