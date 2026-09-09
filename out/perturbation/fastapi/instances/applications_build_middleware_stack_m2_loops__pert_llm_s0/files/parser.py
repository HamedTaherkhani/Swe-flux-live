#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "fastapi.applications.FastAPI.build_middleware_stack"
EXPECTED_LOOP_HEADER = 1066

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+/fastapi/applications\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def locate_loop(source_path: Path) -> tuple[int, int]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    target_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "FastAPI"
        ),
        None,
    )
    if target_class is None:
        fail("class FastAPI is absent from fastapi/applications.py")

    target = next(
        (
            node
            for node in target_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "build_middleware_stack"
        ),
        None,
    )
    if target is None:
        fail("target method is absent from class FastAPI")

    loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
    ]
    if len(loops) != 2:
        fail(f"expected exactly two target loops, found {len(loops)}")

    selected = next(
        (node for node in loops if node.lineno == EXPECTED_LOOP_HEADER), None
    )
    if selected is None or not selected.body:
        fail(
            f"expected a loop with a body at source line {EXPECTED_LOOP_HEADER}"
        )
    return selected.lineno, selected.body[0].lineno


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[Path, int, str]] = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    Path(match.group("path")),
                    int(match.group("line")),
                    match.group("event"),
                )
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    source_paths = {path for path, _, _ in events}
    if len(source_paths) != 1:
        fail(f"expected one target source path, found {len(source_paths)}")
    loop_header, body_first_line = locate_loop(next(iter(source_paths)))

    iteration_counts: list[int] = []
    active_count: int | None = None
    for _, line_number, event in events:
        if event == "call":
            if active_count is not None:
                fail("unexpected recursive or overlapping target invocation")
            active_count = 0
        elif event == "line":
            if active_count is None:
                fail("target line event occurred outside an invocation")
            if line_number == body_first_line:
                active_count += 1
        elif event == "exception":
            fail("target raised an exception during an invocation")
        elif event == "return":
            if active_count is None:
                fail("target return event occurred outside an invocation")
            iteration_counts.append(active_count)
            active_count = None

    if active_count is not None:
        fail("trace ended during a target invocation")
    if not iteration_counts:
        fail("no completed target invocations were found")
    if min(iteration_counts) < 15:
        fail(f"loop exercise is too shallow: counts={iteration_counts}")
    if len(set(iteration_counts)) < 6:
        fail(f"loop exercise has too few distinct counts: {iteration_counts}")

    question = (
        "Run only the pytest test "
        "`fastapi_qa/applications_build_middleware_stack_m2_loops/files/"
        "testcase.py::TestBuildMiddlewareStackLoops::"
        "test_generated_middleware_populations`. During that test run, consider "
        "every invocation of exactly "
        "`fastapi.applications.FastAPI.build_middleware_stack` from "
        "`fastapi/applications.py`; calls of other functions or nested frames "
        "are excluded. An invocation means one runtime call of that exact "
        "dotted function, numbered 1-based in chronological call-entry order. "
        f"For the `for` loop whose header begins at line {loop_header}, compute "
        "the iteration count separately for each invocation, then report the "
        "maximum and minimum of those per-invocation counts over the complete "
        "test run. Define iteration N (1-based) as the Nth execution, in that "
        f"invocation, of the loop body's first executable source line, line "
        f"{body_first_line}; evaluating the loop header does not itself count "
        "as an iteration. Source line numbers are absolute, 1-based line "
        "numbers in the named repository file as it exists for this test. For "
        "a multi-line statement or expression, its executed line is the line "
        "where that statement or expression begins; the method's `def` line, "
        "decorators, comments, and docstring lines do not count. Return exactly "
        "one JSON object with keys `max_iterations` and `min_iterations`, each "
        "mapped to a bare JSON integer. Keys have exactly those spellings; no "
        "string formatting, `repr`, null representation, sorting, "
        "deduplication, or tie-breaking convention applies to these two scalar "
        "extrema."
    )
    result = {
        "question_kind": "M2_Loops",
        "question": question,
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
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
