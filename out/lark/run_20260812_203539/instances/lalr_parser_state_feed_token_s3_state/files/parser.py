#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "lark/parsers/lalr_parser_state.py"
TARGET_FUNC = "lark.parsers.lalr_parser_state.ParserState.feed_token"
AFTER_VALUE_ASSIGNMENT_LINE = 103

QUESTION = (
    "Run the single pytest test "
    "`lark_qa/lalr_parser_state_feed_token_s3_state/files/testcase.py::"
    "TestParserStateFeedToken::test_reduction_chain`. For the first and only "
    "invocation of `lark.parsers.lalr_parser_state.ParserState.feed_token` in "
    "`lark/parsers/lalr_parser_state.py`, report the complete value history of "
    "the local variable `value`: record one entry immediately after each "
    "execution of line 101 (`value = callbacks[rule](s) if callbacks else s`) "
    "has completed, in chronological order. An invocation means one call of "
    "the target function during the test run, counted 1-based in chronological "
    "order. `step` is a 1-based count of these line-101 completions within that "
    "invocation. Retain every occurrence, including consecutive duplicate "
    "values; do not sort or deduplicate entries. Return exactly "
    "`{\"value_history\": [{\"step\": <int>, \"value\": <str>}, ...]}`. "
    "Each `value` is the Python `repr()` string of the value at that observation "
    "point, and containers use the `repr()` of the whole container. Thus strings "
    "keep their quotes, `None` and `True` use Python spellings, and embedded "
    "newlines are newline characters in the decoded JSON string (escaped only "
    "as required by JSON syntax). If a value has no content, represent its "
    "`repr()` (for example, an empty string is `''`), never JSON null and never "
    "an omitted key. Line numbers are absolute, 1-based source line numbers in "
    "the named repository file as it exists for this test. For a multi-line "
    "statement, execution is attributed to the line on which the statement or "
    "expression begins; decorator, `def`, and docstring lines are not included "
    "unless Python executes them as a line event. The observation here is after "
    "the assignment on line 101, before the next statement beginning on line "
    "103."
)

EVENT_RE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    call_count = 0
    active_first_call = False
    current_locals = {}
    history = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if " locals=" not in raw_line:
            raise RuntimeError(f"target event has no locals payload: {raw_line}")
        locals_text = raw_line.split(" locals=", 1)[1]
        try:
            changed_locals = ast.literal_eval(locals_text)
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed_locals, dict):
            raise RuntimeError(f"target locals payload is not a dict: {raw_line}")

        if event == "call":
            call_count += 1
            active_first_call = call_count == 1
            current_locals = {}

        if active_first_call:
            current_locals.update(changed_locals)
            if event == "line" and int(match.group("line")) == AFTER_VALUE_ASSIGNMENT_LINE:
                if "value" not in current_locals:
                    raise RuntimeError("line 103 reached without local variable 'value'")
                history.append(
                    {
                        "step": len(history) + 1,
                        "value": current_locals["value"],
                    }
                )

        if active_first_call and event == "return":
            active_first_call = False

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if call_count == 0:
        raise RuntimeError(f"trace contains no calls of {TARGET_FUNC}")
    if not history:
        raise RuntimeError("no completed line-101 value assignments were observed")
    return {"value_history": history}


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "value_history": [
                {
                    "step": "int",
                    "value": "str",
                }
            ]
        },
        "oracle_answer": parse_trace(Path(args.trace_log)),
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {output_path}")


if __name__ == "__main__":
    main()
