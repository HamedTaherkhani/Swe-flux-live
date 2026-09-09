from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/runner/runner.py"
TARGET_FUNC = "kedro.runner.runner.AbstractRunner._run"
TRACE_FRAME_NAME = "kedro.runner.runner._run"
LOOP_HEADER_LINE = 254
INVOCATION = 1
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/runner_run_s2_loops/files/testcase.py::TestThreadedDependencyScheduling::test_programmatic_dependency_chain`
against this repository. During the 1st invocation of
`kedro.runner.runner.AbstractRunner._run` in `kedro/runner/runner.py`, how many
iterations does the `while` loop whose header is at line 254 execute?

Count invocations 1-based in chronological order. An invocation is one Python
`call` event whose frame is exactly
`kedro.runner.runner.AbstractRunner._run`; the requested invocation is the
first such call during the test run. Count loop iterations 1-based, where
iteration N is the Nth execution of the loop body's first source line, line
255 (`ready = ...`), in that exact invocation. Thus the reported count is the
total number of Python `line` events at line 255 in that frame. Include every
such event, including the final pass if its subsequent control flow breaks
out of the loop. Exclude `call`, `return`, and `exception` events and all
events from callees, comprehensions, generator frames, other functions, and
other invocations.

Line numbers are absolute, 1-based source line numbers in the named file as it
exists in this repository. A Python `line` event is attributed to the source
line where the executed statement or expression begins; continuation lines
of a multi-line statement do not create alternative loop iterations under
this definition. The function's `def` line, decorator lines, and docstring
lines do not count because only executions of line 255 count.

Return exactly one JSON object with the shape
`{"loop_iteration_count": "int"}`, where the shown `"int"` is a type
placeholder: `loop_iteration_count` must be the count encoded as a JSON
integer, not as a string or a Python `repr`. This scalar count has no sorting,
tie-breaking, ordering, or deduplication step; every qualifying line event
contributes one before the integer total is emitted."""


def _loop_body_first_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AbstractRunner"
        ),
        None,
    )
    if target_class is None:
        raise RuntimeError(f"AbstractRunner not found in {source_path}")

    target_function = next(
        (
            node
            for node in target_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_run"
        ),
        None,
    )
    if target_function is None:
        raise RuntimeError(f"AbstractRunner._run not found in {source_path}")

    matching_loops = [
        node
        for node in ast.walk(target_function)
        if isinstance(node, ast.While) and node.lineno == LOOP_HEADER_LINE
    ]
    if len(matching_loops) != 1:
        raise RuntimeError(
            f"expected one while loop at line {LOOP_HEADER_LINE}, "
            f"found {len(matching_loops)}"
        )
    loop = matching_loops[0]
    if not loop.body:
        raise RuntimeError(f"while loop at line {LOOP_HEADER_LINE} has no body")
    return loop.body[0].lineno


def _first_invocation_lines(trace_path: Path) -> tuple[int, list[int]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    in_requested_invocation = False
    requested_lines: list[int] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TRACE_FRAME_NAME
            or not match.group("file").replace("\\", "/").endswith(
                f"/{TARGET_FILE}"
            )
        ):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation_number += 1
            in_requested_invocation = invocation_number == INVOCATION
        elif event == "line" and in_requested_invocation:
            requested_lines.append(int(match.group("line")))
        elif event == "return" and in_requested_invocation:
            in_requested_invocation = False

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations; "
            f"need invocation {INVOCATION}"
        )
    if not requested_lines:
        raise RuntimeError(
            f"invocation {INVOCATION} of {TARGET_FUNC} contains zero line events"
        )
    return target_events, requested_lines


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    body_first_line = _loop_body_first_line(Path.cwd() / TARGET_FILE)
    _target_events, invocation_lines = _first_invocation_lines(args.trace_log)
    iteration_count = sum(line == body_first_line for line in invocation_lines)
    if iteration_count == 0:
        raise RuntimeError(
            f"invocation {INVOCATION} has zero iterations of the while loop "
            f"at line {LOOP_HEADER_LINE}"
        )

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
