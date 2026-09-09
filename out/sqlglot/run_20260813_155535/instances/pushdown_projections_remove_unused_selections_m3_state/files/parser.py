import argparse
import ast
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.optimizer.pushdown_projections._remove_unused_selections"
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/pushdown_projections\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Run every pytest test method whose name begins `test_` in "
    "`sqlglot_qa/pushdown_projections_remove_unused_selections_m3_state/files/testcase.py::"
    "TestRemoveUnusedSelectionsState`. The answer aggregates observations from ALL 12 "
    "collected methods in that class. Identify each method by its full pytest id "
    "`sqlglot_qa/pushdown_projections_remove_unused_selections_m3_state/files/testcase.py::"
    "TestRemoveUnusedSelectionsState::<method_name>`; execute them in pytest's default "
    "collection order. During that complete run, consider every Python `line` event in "
    "exactly `sqlglot.optimizer.pushdown_projections._remove_unused_selections` in "
    "`sqlglot/optimizer/pushdown_projections.py`. Calls and events in all other functions, "
    "including callees and comprehension frames, do not count. An invocation is one Python "
    "`call` of exactly the target function, numbered 1-based in chronological order across "
    "all covered methods. At each qualifying line event, observe the live local variable "
    "`new_selections` immediately before the statement beginning on that line executes, "
    "but only if that local has already been assigned in that invocation; events before its "
    "assignment contribute no value. Record Python's standard, untruncated `repr()` of the "
    "whole current list, including Python container and expression formatting and Python "
    "spellings such as `None` and `True` if they occur. In-place mutations of the list count: "
    "the value visible at the next qualifying line event is observed. Line numbers are "
    "absolute, 1-based lines in the named repository file. For a multi-line statement or "
    "expression, the line event belongs to the line where that statement or expression "
    "begins. Decorator and docstring lines do not count unless Python emits a line event for "
    "them, and the function's `def` line does not count unless Python emits a line event for "
    "it. Across all observations and invocations, remove duplicate repr strings by exact "
    "string equality, then sort the remaining strings ascending by Unicode code-point "
    "lexicographic order; there are no secondary ties after deduplication. Return exactly a "
    "JSON object with the single key `unique_values`, whose value is the sorted array of "
    "those repr strings. JSON escaping is only the transport encoding for each Python repr "
    "string; emit no extra keys, and do not substitute JSON `null`/`true` inside the strings. "
    "No absent local, empty string, or JSON null is emitted as a value."
)


def parse_locals(raw):
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(f"could not parse traced locals: {raw}") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise RuntimeError(f"unexpected traced locals payload: {raw}")
    return value


def compute_unique_values(trace_path):
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    active_states = []
    unique_values = set()
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_locals(match.group("locals"))

        if event == "call":
            active_states.append(dict(changed))
            continue
        if not active_states:
            raise RuntimeError(f"target {event} event occurred outside an active invocation")

        state = active_states[-1]
        state.update(changed)
        if event == "line" and "new_selections" in state:
            unique_values.add(state["new_selections"])
        elif event == "return":
            active_states.pop()

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_states:
        raise RuntimeError("one or more target invocations did not complete")
    if not unique_values:
        raise RuntimeError("target events contained no observations of new_selections")

    return sorted(unique_values)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": compute_unique_values(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
