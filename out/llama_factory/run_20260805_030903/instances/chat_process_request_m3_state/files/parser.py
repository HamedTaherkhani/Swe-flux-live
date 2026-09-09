#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "llamafactory.api.chat._process_request"
QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/chat_process_request_m3_state/files/testcase.py::"
    "TestChatRequestProgramState::test_seeded_mixed_message_batches_through_public_api`. "
    "Across every invocation of `llamafactory.api.chat._process_request` in "
    "`src/llamafactory/api/chat.py` during that complete test run, report the sorted set of "
    "distinct values of the three-variable state tuple `(i, input_messages, text_content)` "
    "at executed-line observation points. An invocation is one runtime `call` of that exact function and "
    "invocations are numbered 1-based in chronological order, although invocation numbers "
    "are not included in the answer. An executed-line observation point is the state of the "
    "target function's own frame immediately before each executed source line begins, and an "
    "observation counts only when all three named locals are already bound. A local remains "
    "bound to its latest value until it is rebound, including while a later branch executes. Include observations "
    "from all invocations, but exclude call, return, and exception events and exclude nested "
    "comprehension or callee frames. Line numbers, if used to reproduce the observations, are "
    "absolute 1-based line numbers in the named file. For a multi-line statement or "
    "expression, an executed-line observation is associated with each line for which CPython "
    "emits a line execution event, before that line's expression executes; the function's "
    "`def` line and decorator lines are not executed-line observations in the function frame. "
    "At each included point, construct a Python tuple in exactly the displayed order from the "
    "current integer `i`, the whole `input_messages` list, and the current string "
    "`text_content`, then apply Python `repr()` to that whole tuple after all mutations "
    "completed before that point. Preserve tuple and list order, dictionary insertion "
    "order, quote and escape choices, and Python spellings such as `None`, `True`, and "
    "`False`; do not recursively convert the value to JSON. For example, the integer tuple "
    "value `(7, None)` would be represented by the JSON string `\"(7, None)\"`. Remove "
    "duplicate repr strings globally across all invocations, then sort the remaining strings "
    "in ascending lexicographic order by Python string comparison (Unicode code-point order); "
    "there is no secondary tie-breaker because duplicates have been removed. Return exactly "
    "one JSON object with the key `unique_values`. Its value must be a flat JSON array of JSON "
    "strings containing those complete Python repr strings. Every observed value is present "
    "as a string: JSON null, an absent key, and an empty JSON string are not substitutes for "
    "any repr value."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/api/chat\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.*?"
    r"locals=(?P<locals>\{.*\})$"
)


def parse_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_locals(raw_locals, trace_line_number):
    try:
        parsed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals at trace line {trace_line_number}: {exc}")
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        fail(f"locals at trace line {trace_line_number} are not a string-to-string dictionary")
    return parsed


def main():
    args = parse_cli()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    observed_values = set()
    current_locals = {}
    for trace_line_number, raw_line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        changed_locals = parse_locals(match.group("locals"), trace_line_number)
        if event == "call":
            current_locals = dict(changed_locals)
            continue
        current_locals.update(changed_locals)
        if event != "line":
            continue

        variable_names = ("i", "input_messages", "text_content")
        if all(name in current_locals for name in variable_names):
            try:
                values = tuple(ast.literal_eval(current_locals[name]) for name in variable_names)
            except (SyntaxError, ValueError) as exc:
                fail(f"cannot reconstruct state tuple at trace line {trace_line_number}: {exc}")
            value_repr = repr(values)
            if any(current_locals[name].endswith("...") for name in variable_names):
                fail(f"state tuple component is truncated at trace line {trace_line_number}")
            observed_values.add(value_repr)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if len(observed_values) < 8:
        fail(f"expected at least 8 distinct state tuple values, observed {len(observed_values)}")

    answer = {"unique_values": sorted(observed_values)}
    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
