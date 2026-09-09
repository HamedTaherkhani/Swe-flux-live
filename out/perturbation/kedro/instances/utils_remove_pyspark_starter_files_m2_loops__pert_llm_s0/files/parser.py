from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/templates/project/hooks/utils.py"
TARGET_FUNC = "kedro.templates.project.hooks.utils._remove_pyspark_starter_files"
LOOP_HEADER_LINE = 126

QUESTION = """Run the pytest test `kedro_qa/utils_remove_pyspark_starter_files_m2_loops/files/testcase.py::TestPySparkStarterCleanup::test_generated_project_cleanup`. During that test run, consider every invocation of `kedro.templates.project.hooks.utils._remove_pyspark_starter_files` in `kedro/templates/project/hooks/utils.py`.

For the `for` loop whose header starts on line 126 (`for file_path in raw_data_path.glob("*.*")`), compute the number of iterations separately for each invocation, then report the maximum and minimum of those per-invocation counts. An invocation is one entry (call) into the target function; number invocations 1-based in chronological call order, including every call made during the named test. An iteration is one execution, in that invocation's function frame, of the loop body's first executable line, the `if` statement beginning on line 127. Thus a loop that never executes its body has an iteration count of zero. Keep repeated per-invocation counts when taking the extrema; do not deduplicate them. Invocation order is used only to define the grouping and does not alter the extrema.

Line numbers are absolute, 1-based source line numbers in the named repository file as it exists for this test. For a multi-line statement or expression, its line is the line on which that statement or expression begins; decorator lines, the `def` line, and docstring-only lines do not count as loop iterations.

Return exactly one JSON object with exactly the keys `max_iterations` and `min_iterations`, each mapped to a JSON integer. `max_iterations` is the greatest per-invocation count and `min_iterations` is the least. These are numeric JSON values, not strings; no value formatting, null sentinel, sorting, or tie-breaker is applicable beyond the extrema rules above."""


EVENT_RE = re.compile(
    rf" (?P<path>\S+):(?P<line>\d+) {re.escape(TARGET_FUNC)} "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def validate_target_source(root: Path) -> int:
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source file is missing: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_remove_pyspark_starter_files"
        ),
        None,
    )
    if target is None:
        fail("target function was not found in the target source")

    loop = next(
        (
            node
            for node in ast.walk(target)
            if isinstance(node, ast.For) and node.lineno == LOOP_HEADER_LINE
        ),
        None,
    )
    if loop is None or not loop.body:
        fail(f"expected for loop was not found at line {LOOP_HEADER_LINE}")
    return loop.body[0].lineno


def iteration_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    counts: list[int] = []
    active_count: int | None = None
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if not match.group("path").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            if active_count is not None:
                fail("encountered a nested target call before the prior invocation returned")
            active_count = 0
        elif event == "line":
            if active_count is None:
                fail("encountered a target line event outside an invocation")
            if line == body_line:
                active_count += 1
        elif event == "return":
            if active_count is None:
                fail("encountered a target return event without a matching call")
            counts.append(active_count)
            active_count = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active_count is not None:
        fail("trace ended before the final target invocation returned")
    if not counts:
        fail("trace contains no complete target invocations")
    if len(set(counts)) < 6:
        fail("scenario produced fewer than six distinct per-invocation loop counts")
    return counts


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    root = Path.cwd()
    body_line = validate_target_source(root)
    counts = iteration_counts(arguments.trace_log, body_line)

    document = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": {
            "max_iterations": max(counts),
            "min_iterations": min(counts),
        },
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
