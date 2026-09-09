#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/translation_fixer.py"
TARGET_FUNC = "scripts.translation_fixer.iter_all_lang_paths"
INVOCATION_MARKER_LINE = 36
LOOP_HEADER_LINE = 48
LOOP_BODY_FIRST_LINE = 49

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/translation_fixer_iter_all_lang_paths_m2_loops/files/testcase.py::TestGeneratedTranslationTrees::test_fix_all_across_variable_language_trees`
against this repository. During that test, consider every invocation of
`scripts.translation_fixer.iter_all_lang_paths` whose implementation is in
`scripts/translation_fixer.py`. An invocation is one Python-level call to
exactly that function that creates a fresh generator, counted 1-based in
chronological order from the start of the stated test. Calls to other
functions are not invocations. Suspending and resuming an already-created
generator, including each resume after a yielded path, remains part of its
original invocation and does not create another invocation.

For each invocation, count iterations of the `for path in
lang_path_root.rglob("*.md")` loop whose header is at line 48. One iteration
is one execution, in that invocation, of the loop body's first line,
`if str(path).startswith(first_dirs_str):`, at line 49; equivalently,
iteration N is the Nth execution of line 49 after that invocation's fresh
generator begins and before that generator is exhausted. Count the iteration
even when line 49's condition is true and the loop immediately executes
`continue`. Every invocation contributes exactly one count, including zero
if line 49 never executes. Do not deduplicate invocations or line executions.

What are the maximum and minimum of those per-invocation counts over the
entire stated test run? Return exactly
`{"max_iterations": "int", "min_iterations": "int"}`, replacing each type
marker with a base-10 JSON integer, not a quoted string. Both extrema range
over all invocations. Invocation ordering only defines their counting scope;
ties require no tie-breaker and do not change either extremum.

All line numbers are absolute, 1-based source line numbers in the named file
as it exists in this repository. For a multi-line statement, its executed
source line is the line where that statement or expression begins. The
identified loop header and first body statement are single-line statements.
The function's `def` line, docstring lines, generator call/return boundaries,
yield suspension/resumption events, and lines executed by callees do not count
as loop-body executions. The answer contains only JSON integers, so no string,
`repr`, null, container-ordering, or name-serialization convention applies."""


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
            if isinstance(node, ast.FunctionDef)
            and node.name == "iter_all_lang_paths"
        ),
        None,
    )
    if target is None:
        fail(f"could not locate {TARGET_FUNC} in {source_path}")
    loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.For)
        and node.lineno == LOOP_HEADER_LINE
        and node.body
        and node.body[0].lineno == LOOP_BODY_FIRST_LINE
    ]
    if len(loops) != 1:
        fail(
            "target source does not contain exactly one expected loop at "
            f"lines {LOOP_HEADER_LINE}-{LOOP_BODY_FIRST_LINE}"
        )
    if not any(
        isinstance(node, ast.Assign) and node.lineno == INVOCATION_MARKER_LINE
        for node in target.body
    ):
        fail(f"expected invocation marker statement at line {INVOCATION_MARKER_LINE}")


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
    saw_loop_header = False
    for event, line in target_events:
        if event == "line" and line == INVOCATION_MARKER_LINE:
            if active_count is not None:
                if not saw_loop_header:
                    fail("target invocation never reached the selected loop")
                iteration_counts.append(active_count)
            active_count = 0
            saw_loop_header = False
        elif active_count is not None and event == "line":
            if line == LOOP_HEADER_LINE:
                saw_loop_header = True
            elif line == LOOP_BODY_FIRST_LINE:
                active_count += 1

    if active_count is None:
        fail(f"trace contains no invocation marker for {TARGET_FUNC}")
    if not saw_loop_header:
        fail("final target invocation never reached the selected loop")
    iteration_counts.append(active_count)
    if len(iteration_counts) < 2:
        fail("expected multiple complete target invocations")
    if any(count == 0 for count in iteration_counts):
        fail("selected loop unexpectedly had zero iterations")

    output = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": {
            "max_iterations": max(iteration_counts),
            "min_iterations": min(iteration_counts),
        },
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
