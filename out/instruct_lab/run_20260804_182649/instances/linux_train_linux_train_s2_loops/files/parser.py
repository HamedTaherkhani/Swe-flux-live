#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/train/linux_train.py"
TARGET_FUNC = "instructlab.train.linux_train.linux_train"
LOOP_HEADER_LINE = 273
LOOP_BODY_FIRST_LINE = 274
INVOCATION = 1
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test `instruct_lab_qa/linux_train_linux_train_s2_loops/files/testcase.py::TestLinuxTrainingLoop::test_generated_attention_parameters` and consider `instructlab.train.linux_train.linux_train` in `src/instructlab/train/linux_train.py`. During the first invocation of that function, exactly how many iterations does the `for par in list(layer.named_parameters())` loop whose header begins at line 273 execute?

An invocation is one Python call of exactly `instructlab.train.linux_train.linux_train`, counted 1-based in chronological order over the complete test run; nested functions, callees, and other frames do not create target invocations. Use the first invocation. An iteration of the loop at line 273 is the Nth execution of that loop body's first source line, `mod = par[0]`, at line 274, within the selected invocation's own frame. Count every such execution in chronological order, including executions whose later statements take different branches; do not count evaluation of the loop header, activity in `layer.named_parameters()`, or events in any callee or other frame. Do not deduplicate executions.

Line numbers are absolute, 1-based physical lines in the named file as it exists in the repository. The loop header and its body-first line are each single-line statements, so no multi-line normalization is needed; the function's `def` line, decorators, and docstring do not count toward an iteration.

Return exactly one JSON object with the shape `{"loop_iteration_count": "int"}`, replacing `"int"` with the count encoded as a JSON integer. There is only one scalar, so sorting and tie-breaking do not apply. The value is a number, not a `str()` or `repr()` string; no null, empty-value, function-name, callee-name, or exception-name serialization convention applies."""


def parse_iteration_count(trace_path: Path) -> int:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    selected_active = False
    selected_finished = False
    count = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation_number += 1
            selected_active = invocation_number == INVOCATION
            continue
        if event == "return":
            if selected_active:
                selected_active = False
                selected_finished = True
            continue
        if (
            selected_active
            and event == "line"
            and int(match.group("line")) == LOOP_BODY_FIRST_LINE
        ):
            count += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations; "
            f"cannot select invocation {INVOCATION}"
        )
    if not selected_finished:
        raise RuntimeError(f"invocation {INVOCATION} has no return event")
    if count == 0:
        raise RuntimeError(
            f"loop at line {LOOP_HEADER_LINE} executed zero detectable iterations"
        )
    return count


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True, type=Path)
    arg_parser.add_argument("--out", required=True, type=Path)
    args = arg_parser.parse_args()

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {
            "loop_iteration_count": parse_iteration_count(args.trace_log)
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
