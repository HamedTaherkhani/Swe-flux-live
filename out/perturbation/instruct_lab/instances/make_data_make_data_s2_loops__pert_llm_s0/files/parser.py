#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/train/lora_mlx/make_data.py"
TARGET_FUNC = "instructlab.train.lora_mlx.make_data.make_data"
LOOP_HEADER_LINE = 44
INVOCATION = 1
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def loop_body_first_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        and node.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1:
        fail(
            f"expected exactly one loop at line {LOOP_HEADER_LINE} in {source_path}; "
            f"found {len(loops)}"
        )
    if not loops[0].body:
        fail(f"loop at line {LOOP_HEADER_LINE} has no body")
    return loops[0].body[0].lineno


def count_iterations(trace_path: Path, source_path: Path) -> int:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    first_body_line = loop_body_first_line(source_path)
    invocation = 0
    active = False
    target_events = 0
    iteration_count = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation += 1
            active = invocation == INVOCATION
        elif event == "line" and active:
            if int(match.group("line")) == first_body_line:
                iteration_count += 1
        elif event == "return" and active:
            active = False

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation < INVOCATION:
        fail(f"trace contains no invocation {INVOCATION} of {TARGET_FUNC}")
    if active:
        fail(f"invocation {INVOCATION} has no return event")
    if iteration_count == 0:
        fail(
            f"loop at line {LOOP_HEADER_LINE} had zero iterations in "
            f"invocation {INVOCATION}"
        )
    return iteration_count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    answer = count_iterations(Path(args.trace_log), source_path)
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/make_data_make_data_s2_loops/files/testcase.py::"
        "TestSimpleTrainDataPreparation::test_preprocessing_via_training_entrypoint` "
        "against this repository. During the first invocation of "
        "`instructlab.train.lora_mlx.make_data.make_data` in "
        "`src/instructlab/train/lora_mlx/make_data.py`, exactly how many iterations "
        "does the `for obj in data_new[:n]` loop whose header is on line 44 perform? "
        "An invocation is one runtime call of exactly that function, counted 1-based "
        "in chronological order from the start of the test; calls to any other "
        "function do not count. Iterations are also counted 1-based: iteration N is "
        "the Nth time the loop body's first statement, the `f.write(...)` statement "
        "beginning on line 45, executes in that invocation. Count every such execution "
        "once, with no sorting or deduplication; events in callees and executions of "
        "other loops do not count. Line numbers are absolute, 1-based physical line "
        "numbers in the named repository file as it exists for this test. The loop "
        "header and body statement are each single-line statements, so no multi-line "
        "continuation-line normalization applies; the function's `def` line, comments, "
        "and non-executable blank lines do not count as iterations. Return exactly one "
        "JSON object with the sole key `loop_iteration_count`; its value is a JSON "
        "integer (not a quoted string, Python `repr`, or `null`). There is only this "
        "single scalar value, so key ordering and tie-breaking are not applicable."
    )
    payload = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": answer},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
