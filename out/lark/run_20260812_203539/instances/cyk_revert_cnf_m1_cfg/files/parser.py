#!/usr/bin/env python3
import argparse
import ast
from collections import Counter
import json
from pathlib import Path


TARGET_FILE = "lark/parsers/cyk.py"
TARGET_FILE_SUFFIX = "/" + TARGET_FILE
TARGET_FUNC = "lark.parsers.cyk.revert_cnf"
TARGET_NAME = "revert_cnf"

TEST_PATH = "lark_qa/cyk_revert_cnf_m1_cfg/files/testcase.py"
TEST_CLASS = "TestRevertCnfAggregateControlFlow"
TEST_METHODS = (
    "test_amber_canopy",
    "test_brisk_delta",
    "test_cobalt_finch",
    "test_dappled_grove",
    "test_ember_harbor",
    "test_frosted_isle",
    "test_golden_junction",
    "test_hushed_keystone",
    "test_indigo_lantern",
    "test_jade_meadow",
    "test_kindled_north",
    "test_lucid_orchard",
)

QUESTION = (
    "Run only the pytest class node `"
    + TEST_PATH
    + "::"
    + TEST_CLASS
    + "`, and aggregate over ALL of its test methods: "
    + ", ".join(f"`{name}`" for name in TEST_METHODS)
    + ". For `lark.parsers.cyk.revert_cnf` in `lark/parsers/cyk.py`, report "
    "the total runtime line-event count for every physical source line in "
    "the function body, defined here as absolute 1-based lines 320 through "
    "340 inclusive. A runtime line event means a Python tracing `line` event "
    "whose frame is exactly an invocation of that target function and whose "
    "`frame.f_lineno` is the reported physical line. An invocation is one "
    "`call` event for exactly `lark.parsers.cyk.revert_cnf`; invocations are "
    "1-based in chronological order if they need to be distinguished, but "
    "the requested counts sum across every invocation made by every listed "
    "test method. Recursive `revert_cnf` invocations therefore contribute "
    "their own line events. Events in callers, in `unroll_unit_skiprule`, or "
    "in any other nested frame do not contribute. Count every repeated line "
    "event separately; do not deduplicate events. For a multi-line statement "
    "or expression, attribute each event to the absolute physical line "
    "reported by `frame.f_lineno`; do not collapse continuation-line events "
    "onto the statement's first line. Thus a continuation line contributes "
    "when and only when the runtime emits a `line` event carrying that "
    "continuation line's own number. "
    "The function's `def` line 319 and any decorator lines are excluded from "
    "the body range and never count. Every line in the inclusive body range "
    "must nevertheless appear in the answer: a docstring, blank line, comment "
    "line, continuation line, or executable line that produces no target "
    "line event is reported with count 0. Counts are totals across the whole "
    "class run; pytest's method execution order does not alter these sums. "
    "Return exactly one JSON object with the single key "
    "`line_execution_counts`. Its value is a list containing one object per "
    "physical line in the body range; each object has exactly `count` (a "
    "non-negative JSON integer) and `line` (an absolute 1-based JSON integer). "
    "Sort the list by `line` in strictly ascending order, with no omissions "
    "or duplicates. There are no string-value conversions, sentinel strings, "
    "or null values."
)


def function_body_range(source_path):
    if not source_path.exists():
        raise RuntimeError(f"target source is missing: {source_path}")
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(source_path))
    matches = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == TARGET_NAME
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one top-level {TARGET_NAME}, found {len(matches)}"
        )
    function = matches[0]
    if function.end_lineno is None:
        raise RuntimeError(f"target function has no end line: {TARGET_NAME}")
    first_body_line = function.lineno + 1
    last_body_line = function.end_lineno
    if (first_body_line, last_body_line) != (320, 340):
        raise RuntimeError(
            "target source range changed: expected 320-340, "
            f"found {first_body_line}-{last_body_line}"
        )
    return range(first_body_line, last_body_line + 1)


def parse_target_event(raw_line):
    marker = f" {TARGET_FUNC} event="
    if marker not in raw_line:
        return None

    prefix, remainder = raw_line.split(marker, 1)
    location = prefix.rsplit(" ", 1)[-1]
    try:
        filename, line_text = location.rsplit(":", 1)
        line_number = int(line_text)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"malformed target trace event: {raw_line!r}") from exc

    if not filename.replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
        return None
    event = remainder.split(" ", 1)[0]
    return event, line_number


def compute_line_execution_counts(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    body_lines = tuple(function_body_range(source_path))
    body_line_set = set(body_lines)
    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_target_event(raw_line)
        if parsed is not None:
            target_events.append(parsed)
    if not target_events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    call_count = sum(event == "call" for event, _line in target_events)
    if call_count == 0:
        raise RuntimeError(f"trace contains zero call events for {TARGET_FUNC}")

    line_numbers = [
        line_number
        for event, line_number in target_events
        if event == "line" and line_number in body_line_set
    ]
    if not line_numbers:
        raise RuntimeError(f"trace contains zero line events for {TARGET_FUNC}")

    unexpected = sorted(
        {
            line_number
            for event, line_number in target_events
            if event == "line" and line_number not in body_line_set
        }
    )
    if unexpected:
        raise RuntimeError(
            f"target line events outside function body range: {unexpected}"
        )

    counts = Counter(line_numbers)
    return [
        {"count": counts.get(line_number, 0), "line": line_number}
        for line_number in body_lines
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": {
            "line_execution_counts": compute_line_execution_counts(
                args.trace_log, source_path
            )
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, sort_keys=True))


if __name__ == "__main__":
    main()
