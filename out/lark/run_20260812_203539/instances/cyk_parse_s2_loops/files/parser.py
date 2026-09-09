#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TARGET_FILE_SUFFIX = "/lark/parsers/cyk.py"
TARGET_FUNC = "lark.parsers.cyk._parse"
LOOP_HEADER_LINE = 142
LOOP_BODY_FIRST_LINE = 143

QUESTION = (
    "Run only the pytest test "
    "`lark_qa/cyk_parse_s2_loops/files/testcase.py::TestCykLoopBehavior::"
    "test_generated_terminal_mix`. During the first invocation of "
    "`lark.parsers.cyk._parse` in `lark/parsers/cyk.py`, how many total "
    "iterations does the `for terminal, rules in ...` loop whose header is at line 142 "
    "perform, summed across every time that loop is entered by its enclosing "
    "loops? An invocation means one call of the function during this test run; "
    "invocations are numbered from 1 in chronological call order. Iterations "
    "are also 1-based: iteration N is the Nth execution, within that invocation, "
    "of the loop body's first line, line 143. Count every such execution, "
    "including repeated executions with equal loop-variable values; do not "
    "deduplicate or sort anything. Line numbers are absolute 1-based source "
    "line numbers in the named repository file as it exists for the run. For a "
    "multi-line statement, an executed line is the line on which that statement "
    "or expression begins; decorator, `def`, and docstring lines do not count "
    "unless Python executes them in the function frame. Return exactly a JSON "
    "object with the single key `loop_iteration_count` and an integer value."
)


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
    return line_number, event


def compute_iteration_count(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_target_event(raw_line)
        if parsed is not None:
            target_events.append(parsed)

    if not target_events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in lark/parsers/cyk.py"
        )

    first_invocation_started = False
    first_invocation_active = False
    first_invocation_finished = False
    count = 0

    for line_number, event in target_events:
        if event == "call" and not first_invocation_started:
            first_invocation_started = True
            first_invocation_active = True
            continue

        if not first_invocation_active:
            continue

        if event == "line" and line_number == LOOP_BODY_FIRST_LINE:
            count += 1
        elif event == "return":
            first_invocation_active = False
            first_invocation_finished = True
            break

    if not first_invocation_started:
        raise RuntimeError(f"no call event found for {TARGET_FUNC}")
    if not first_invocation_finished:
        raise RuntimeError(f"first invocation of {TARGET_FUNC} did not return")
    if count == 0:
        raise RuntimeError(
            f"loop at line {LOOP_HEADER_LINE} executed zero observable iterations"
        )
    return count


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    iteration_count = compute_iteration_count(args.trace_log)
    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, sort_keys=True))


if __name__ == "__main__":
    main()
