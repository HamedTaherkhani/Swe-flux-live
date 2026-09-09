#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TARGET_FILE = "lark/parsers/lalr_analysis.py"
TARGET_FILE_SUFFIX = "/" + TARGET_FILE
TARGET_FUNC = "lark.parsers.lalr_analysis.LALR_Analyzer.compute_lalr1_states"
INVOCATION_NUMBER = 2

QUESTION = (
    "Run only the pytest test "
    "`lark_qa/lalr_analysis_compute_lalr1_states_s1_cfg/files/testcase.py::"
    "TestGeneratedLalrControlFlow::test_three_direct_table_constructions`. "
    "For the second invocation of "
    "`lark.parsers.lalr_analysis.LALR_Analyzer.compute_lalr1_states` in "
    "`lark/parsers/lalr_analysis.py`, what is the exact ordered sequence of "
    "executed source-line events in that function's own frame? An invocation "
    "is one `call` event for exactly that function, numbered 1-based in "
    "chronological order during this test; thus nested comprehension frames "
    "and calls made by the function do not count as invocations or contribute "
    "line events. Include every `line` event after the selected call and "
    "before its matching `return`, in chronological event order. Preserve "
    "repeated line numbers and do not sort or deduplicate the sequence. Each "
    "element must be an object with exactly `file` (string), `func` (string), "
    "and `line` (integer). Set `file` to the repository-relative POSIX path "
    "of the target file and `func` to the full dotted "
    "`module.Class.method` name (for example, "
    "`sample.engine.Worker.run`). Line numbers are absolute 1-based source "
    "line numbers in the named file as it exists for the run. The `def` line "
    "does not appear because the sequence contains only `line` events, not "
    "the invocation's `call` event; decorator and docstring lines likewise "
    "appear only if executed as line events in the selected function frame. "
    "For a multi-line statement, call, or condition, report the line where "
    "that statement or expression begins. Return exactly a JSON object with "
    "the single key `executed_path`, whose value is the ordered array of "
    "these objects; there is no other value formatting or null sentinel."
)


def parse_event(raw_line):
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

    normalized_filename = filename.replace("\\", "/")
    if not normalized_filename.endswith(TARGET_FILE_SUFFIX):
        return None

    event = remainder.split(" ", 1)[0]
    return event, line_number


def compute_executed_path(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_event(raw_line)
        if parsed is not None:
            target_events.append(parsed)

    if not target_events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    invocation_count = 0
    selected_active = False
    selected_finished = False
    line_numbers = []

    for event, line_number in target_events:
        if event == "call":
            invocation_count += 1
            selected_active = invocation_count == INVOCATION_NUMBER
            continue

        if not selected_active:
            continue
        if event == "line":
            line_numbers.append(line_number)
        elif event == "return":
            selected_active = False
            selected_finished = True
            break

    if invocation_count < INVOCATION_NUMBER:
        raise RuntimeError(
            f"expected invocation {INVOCATION_NUMBER}, found only {invocation_count}"
        )
    if not selected_finished:
        raise RuntimeError(
            f"invocation {INVOCATION_NUMBER} of {TARGET_FUNC} did not return"
        )
    if not line_numbers:
        raise RuntimeError(
            f"invocation {INVOCATION_NUMBER} produced zero line events"
        )

    return [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line_number}
        for line_number in line_numbers
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": compute_executed_path(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, sort_keys=True))


if __name__ == "__main__":
    main()
