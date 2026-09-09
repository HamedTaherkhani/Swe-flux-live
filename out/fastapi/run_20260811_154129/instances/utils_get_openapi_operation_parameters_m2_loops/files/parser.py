#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/openapi/utils.py"
TARGET_FUNC = "fastapi.openapi.utils._get_openapi_operation_parameters"
LOOP_HEADER_LINE = 187
LOOP_BODY_FIRST_LINE = 188

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/utils_get_openapi_operation_parameters_m2_loops/files/testcase.py::TestGeneratedParameterLoops::test_openapi_for_variable_width_query_models`
against this repository. During that test, consider every invocation of
`fastapi.openapi.utils._get_openapi_operation_parameters` whose implementation
is in `fastapi/openapi/utils.py`. An invocation is one runtime entry into
exactly that function, counted 1-based in chronological order from the start
of the stated test; calls of other functions and any frames they create are
not invocations.

For each invocation, count the iterations of the inner `for param in
param_group` loop whose header is at line 187. One iteration is the Nth
execution, in that invocation, of the loop body's first line,
`field_info = param.field_info`, at line 188. Count those executions across
all passes of the enclosing `for param_type, param_group in parameter_groups`
loop at line 186 as one per-invocation total. Every invocation contributes
exactly one total, including a total of zero if the inner body never executes.
Do not deduplicate invocations or iteration executions.

What are the maximum and minimum of those per-invocation totals over the
entire stated test run? Return exactly
`{"max_iterations": "int", "min_iterations": "int"}`, replacing each type
marker with a base-10 JSON integer (not a quoted string). Both extrema range
over all target invocations; invocation ordering only defines the counting
scope and does not break ties or change either extremum.

All line numbers above are absolute, 1-based source line numbers in the named
file as it exists in this repository. For a multi-line statement, a source
line means the line on which that statement begins; the identified loop
header and first body statement are each single-line statements. The
function's `def` line, decorator lines, call/return boundaries, and lines
executed by callees do not count as loop-body executions."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_target_source(source_path: Path) -> None:
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_get_openapi_operation_parameters"
        ),
        None,
    )
    if target is None:
        fail(f"could not locate {TARGET_FUNC} in {source_path}")

    matching_loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.For)
        and node.lineno == LOOP_HEADER_LINE
        and node.body
        and node.body[0].lineno == LOOP_BODY_FIRST_LINE
    ]
    if len(matching_loops) != 1:
        fail(
            "target source does not contain exactly one expected loop at "
            f"lines {LOOP_HEADER_LINE}-{LOOP_BODY_FIRST_LINE}"
        )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    source_path = None
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        traced_file = match.group("file").replace("\\", "/")
        if not traced_file.endswith(TARGET_FILE):
            fail(f"target event came from unexpected file: {traced_file}")
        if source_path is None:
            source_path = Path(match.group("file"))
        target_events.append((match.group("event"), int(match.group("line"))))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if source_path is None:
        fail("could not determine target source path from trace")
    validate_target_source(source_path)

    iteration_counts = []
    active_count = None
    for event, line in target_events:
        if event == "call":
            if active_count is not None:
                fail("encountered a nested target invocation")
            active_count = 0
        elif active_count is None:
            fail(f"encountered target {event} event outside an invocation")
        elif event == "line" and line == LOOP_BODY_FIRST_LINE:
            active_count += 1
        elif event == "return":
            iteration_counts.append(active_count)
            active_count = None

    if active_count is not None:
        fail("trace ended during an incomplete target invocation")
    if not iteration_counts:
        fail(f"trace contains no complete invocations of {TARGET_FUNC}")

    answer = {
        "max_iterations": max(iteration_counts),
        "min_iterations": min(iteration_counts),
    }
    output = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote oracle from {len(iteration_counts)} target invocations "
        f"to {out_path}"
    )


if __name__ == "__main__":
    main()
