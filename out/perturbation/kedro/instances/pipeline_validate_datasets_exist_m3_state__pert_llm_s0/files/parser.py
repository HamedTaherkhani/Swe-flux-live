#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/pipeline/pipeline.py"
TARGET_FUNC = "kedro.pipeline.pipeline._validate_datasets_exist"
OBSERVATION_LINES = {108, 109}
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\slocals=(?P<locals>\{.*\})$")


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_local_changes(raw_line):
    match = LOCALS_RE.search(raw_line)
    if not match:
        fail("target trace event has no parseable locals mapping")
    try:
        changes = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals mapping: {exc}")
    if not isinstance(changes, dict):
        fail("target locals payload is not a dictionary")
    return changes


def decode_repr(value, variable):
    if not isinstance(value, str):
        fail(f"trace representation for {variable} is not a string")
    if value.endswith("..."):
        fail(f"trace representation for {variable} was truncated")
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not decode repr for {variable}: {exc}")


def collect_unique_values(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    frame_locals = None
    observed = set()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.match(raw_line)
        if not event_match:
            continue
        normalized_file = event_match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue
        if event_match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = event_match.group("event")
        line = int(event_match.group("line"))
        changes = parse_local_changes(raw_line)

        if event == "call":
            target_calls += 1
            frame_locals = {}
        if frame_locals is None:
            fail("encountered a target event outside an active invocation")
        frame_locals.update(changes)

        if event == "line" and line in OBSERVATION_LINES:
            if {
                "non_existent_input",
                "possible_matches",
            } <= frame_locals.keys():
                current_input = decode_repr(
                    frame_locals["non_existent_input"], "non_existent_input"
                )
                current_matches = decode_repr(
                    frame_locals["possible_matches"], "possible_matches"
                )
                if not isinstance(current_input, str):
                    fail("non_existent_input did not decode to str")
                if not isinstance(current_matches, list):
                    fail("possible_matches did not decode to list")
                observed.add(repr((current_input, current_matches)))

        if event == "return":
            frame_locals = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")
    if not observed:
        fail("no eligible two-variable state snapshots were observed")
    return sorted(observed)


def build_question():
    return (
        "Run the pytest test "
        "`kedro_qa/pipeline_validate_datasets_exist_m3_state/files/testcase.py::"
        "TestValidateDatasetsExistState::test_seeded_invalid_dataset_mappings`. "
        "During the complete test run, consider every invocation of "
        "`kedro.pipeline.pipeline._validate_datasets_exist` in "
        "`kedro/pipeline/pipeline.py`. What is the sorted set of distinct "
        "two-variable state snapshots observed in the target's direct frame?\n\n"
        "An invocation is one `call` of the target function, numbered 1-based in "
        "chronological call order; aggregate observations across all invocations, "
        "without including invocation numbers in the answer. Observe only Python "
        "line events in the target function's own frame for which the current "
        "absolute line is 108 or 109 and both local variables "
        "`non_existent_input` and `possible_matches` are already bound. A line event "
        "observes locals immediately before the statement or expression beginning "
        "on that line executes. Thus a line-108 event caused by advancing the `for` "
        "loop observes the state at that exact loop-header event, while a line-109 "
        "event observes the state immediately before its augmented assignment. "
        "The augmented assignment on line 109 reads the old list and then mutates "
        "and rebinds `possible_matches`; its resulting state is visible only at a "
        "subsequent eligible line event. Exclude call, return, and exception events, "
        "and exclude all callee and comprehension frames. Line numbers are absolute, "
        "1-based lines in the named repository file as it exists for this test. "
        "Only lines 108 and 109 are eligible, so the function `def`, decorator, and "
        "docstring lines never count. For a multi-line statement, the event belongs "
        "to the line where the currently executed statement or expression begins.\n\n"
        "For each eligible event, form a fresh two-item Python tuple in this exact "
        "order: `(non_existent_input, possible_matches)`, using the variables' values "
        "at that event, and take `repr()` of the entire tuple immediately. This is a "
        "Python representation, including Python quotes, list brackets, commas, and "
        "spellings such as `None` or `True`, not JSON spellings inside the string; "
        "for example, a different snapshot could be represented as "
        "`('alpha', ['beta'])`. The list is represented with its complete current "
        "contents and order, including duplicates. An unbound variable means that "
        "event is omitted rather than represented by an empty string or JSON null.\n\n"
        "Remove duplicate representation strings across all eligible events, then "
        "sort the remaining strings ascending by Python's ordinary `str` ordering "
        "(lexicographic Unicode code-point order); no tie-breaker is needed after "
        "deduplication. Return exactly one JSON object with the single key "
        "`unique_values`. Its value must be a JSON array of those Python `repr` "
        "strings in that order. Do not add any other keys and do not omit or replace "
        "any value with JSON null."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    unique_values = collect_unique_values(Path(args.trace_log))
    payload = {
        "question_kind": "M3_ProgramState",
        "question": build_question(),
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {output_path} with {len(unique_values)} unique state snapshots")


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
