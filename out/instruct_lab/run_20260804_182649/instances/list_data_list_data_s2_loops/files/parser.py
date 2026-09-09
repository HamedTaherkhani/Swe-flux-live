#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/data/list_data.py"
TARGET_FUNC = "instructlab.data.list_data.list_data"
LOOP_HEADER_LINE = 39
INVOCATION = 1
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def body_first_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        and node.lineno == LOOP_HEADER_LINE
    ]
    if len(matches) != 1:
        fail(
            f"expected exactly one loop at line {LOOP_HEADER_LINE} in "
            f"{source_path}; found {len(matches)}"
        )
    if not matches[0].body:
        fail(f"loop at line {LOOP_HEADER_LINE} has no body")
    return matches[0].body[0].lineno


def iteration_count(trace_path: Path, source_path: Path) -> int:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    first_line = body_first_line(source_path)
    invocation_count = 0
    selected_invocation_active = False
    selected_invocation_finished = False
    target_event_count = 0
    count = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if match.group("func") != TARGET_FUNC:
            continue
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_event_count += 1
        event = match.group("event")
        if event == "call":
            invocation_count += 1
            selected_invocation_active = invocation_count == INVOCATION
        elif event == "line" and selected_invocation_active:
            if int(match.group("line")) == first_line:
                count += 1
        elif event == "return" and selected_invocation_active:
            selected_invocation_active = False
            selected_invocation_finished = True

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < INVOCATION:
        fail(f"trace contains no invocation {INVOCATION} of {TARGET_FUNC}")
    if not selected_invocation_finished:
        fail(f"invocation {INVOCATION} of {TARGET_FUNC} has no return event")
    if count == 0:
        fail(
            f"loop at line {LOOP_HEADER_LINE} had zero iterations in "
            f"invocation {INVOCATION}"
        )
    return count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    answer = iteration_count(Path(args.trace_log), source_path)
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/list_data_list_data_s2_loops/files/testcase.py::"
        "TestDatasetListingTraversal::test_generated_directory_forest_through_cli` "
        "against this repository. During the first invocation of exactly "
        "`instructlab.data.list_data.list_data` in "
        "`src/instructlab/data/list_data.py`, how many iterations does the `while` "
        "loop whose header begins on line 39 perform? An invocation is one runtime "
        "call of exactly that function, counted 1-based in chronological order from "
        "the start of the test; calls to other functions do not count. Iteration "
        "counting is also 1-based: iteration N is the Nth execution, in that "
        "invocation, of the loop body's first statement, `current_dir = "
        "directories.pop()`, which begins on line 40. Count every such execution "
        "once, in chronological order, with no sorting or deduplication. Ignore all "
        "events in callees, all other loops, and all other invocations. Line numbers "
        "are absolute, 1-based physical line numbers in the named repository file as "
        "it exists for this test. The identified loop header and first body statement "
        "are each single-line statements, so multi-line continuation handling is not "
        "applicable; the function's `def` line, its docstring, comments, blank lines, "
        "and the loop-header condition check do not themselves count as iterations. "
        "Return exactly one JSON object with the sole key `loop_iteration_count`; its "
        "value must be a JSON integer, not a quoted string, Python `repr`, or `null`. "
        "There is one scalar result, so output ordering and tie-breaking are not "
        "applicable."
    )
    payload = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": answer},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
