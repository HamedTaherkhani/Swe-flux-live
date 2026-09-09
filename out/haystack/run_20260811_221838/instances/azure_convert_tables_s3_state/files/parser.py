#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "haystack.components.converters.azure._convert_tables"
TARGET_LINE = 310
TARGET_OCCURRENCE = 3
VARIABLES = (
    "following_context",
    "preceding_context",
    "table_content",
    "table_list",
    "table_meta",
)

QUESTION = """Run the single pytest test method `TestAzureConvertTablesState.test_run_with_generated_tables` in `haystack_qa/azure_convert_tables_s3_state/files/testcase.py`. During that test run, consider the first invocation of `haystack.components.converters.azure.AzureOCRDocumentConverter._convert_tables` in `haystack/components/converters/azure.py`. An invocation means one call of that function and invocations are numbered from 1 in chronological order.

What are the values of the local variables `following_context`, `preceding_context`, `table_content`, `table_list`, and `table_meta` immediately after absolute, 1-based source line 310 has executed for the third time within that invocation, and before the next source statement executes? An occurrence is counted each time the statement whose expression begins on line 310 completes, in chronological order and starting at 1. Line numbers refer to the named repository file as it exists for this test; for a multi-line statement, its line is the line on which the statement or expression begins. Decorator, `def`, and docstring lines do not count unless Python actually executes them in this invocation.

Return exactly `{"observed_state": [{"value": "...", "variable": "..."}]}`. `observed_state` is a JSON list with one object per requested variable, sorted by `variable` in ascending Unicode code-point order; do not deduplicate entries. Every object has exactly two JSON string fields: `value` is Python's exact `repr()` string for the complete local value at the observation point, and `variable` is the local's source-level name. For containers, take `repr()` of the whole container rather than formatting elements separately. Thus strings retain their quote characters and Python spellings such as `None` and `True` are used inside representations. Escapes are also those produced by `repr()`; for example, `repr("alpha\\nbeta")` produces `'alpha\\nbeta'` with a backslash and `n` between the words, and JSON escaping may escape that backslash again in the serialized file. All five locals exist at this point, so no missing-value or JSON `null` convention applies."""


EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)(?: |$)"
)


def parse_changed_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        raise ValueError(f"target event has no locals field: {raw_line.rstrip()}")
    locals_text = raw_line.split(marker, 1)[1].strip()
    parsed = ast.literal_eval(locals_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"locals field is not a dictionary: {locals_text}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
        raise ValueError("locals field does not map variable names to repr strings")
    return parsed


def harvest(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    occurrence = 0
    current_locals = {}
    waiting_for_post_line_event = False
    observed = None

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            event = match.group("event")
            line_number = int(match.group("line"))
            changed = parse_changed_locals(raw_line)

            if event == "call":
                invocation += 1
                current_locals = {}
                occurrence = 0
                waiting_for_post_line_event = False

            if invocation != 1:
                continue

            current_locals.update(changed)

            if waiting_for_post_line_event:
                missing = [name for name in VARIABLES if name not in current_locals]
                if missing:
                    raise ValueError(f"observation is missing locals: {missing}")
                observed = [
                    {"value": current_locals[name], "variable": name}
                    for name in sorted(VARIABLES)
                ]
                waiting_for_post_line_event = False
                break

            if event == "line" and line_number == TARGET_LINE:
                occurrence += 1
                if occurrence == TARGET_OCCURRENCE:
                    waiting_for_post_line_event = True

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if occurrence < TARGET_OCCURRENCE:
        raise ValueError(
            f"line {TARGET_LINE} executed only {occurrence} times in the first invocation; "
            f"needed {TARGET_OCCURRENCE}"
        )
    if observed is None:
        raise ValueError(f"trace ended before the state after line {TARGET_LINE} could be observed")
    if any(item["value"].endswith("...") for item in observed):
        raise ValueError("an observed repr appears to have been truncated by the trace logger")
    return observed


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    out_path = Path(args.out)
    observed = harvest(trace_path)

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
