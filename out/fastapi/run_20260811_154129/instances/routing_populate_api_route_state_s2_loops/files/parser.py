#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "fastapi.routing._populate_api_route_state"
TARGET_INVOCATION = 2
EXPECTED_LOOP_HEADER = 1039

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+/fastapi/routing\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def locate_loop(source_path: Path) -> tuple[int, int]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_populate_api_route_state"
        ),
        None,
    )
    if target is None:
        fail("target function is absent from fastapi/routing.py")

    loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
    ]
    if len(loops) != 1:
        fail(f"expected exactly one target loop, found {len(loops)}")
    loop = loops[0]
    if loop.lineno != EXPECTED_LOOP_HEADER or not loop.body:
        fail(
            f"target loop/source mismatch: header={loop.lineno}, "
            f"body_items={len(loop.body)}"
        )
    return loop.lineno, loop.body[0].lineno


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

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

    invocation = 0
    active_invocation: int | None = None
    target_returns = 0
    iteration_count = 0
    for _, line_number, event in events:
        if event == "call":
            if active_invocation is not None:
                fail("unexpected recursive or overlapping target invocation")
            invocation += 1
            active_invocation = invocation
        elif event == "line":
            if active_invocation is None:
                fail("target line event occurred outside an invocation")
            if (
                active_invocation == TARGET_INVOCATION
                and line_number == body_first_line
            ):
                iteration_count += 1
        elif event == "return":
            if active_invocation is None:
                fail("target return event occurred outside an invocation")
            target_returns += 1
            active_invocation = None

    if active_invocation is not None:
        fail("trace ended during a target invocation")
    if invocation < TARGET_INVOCATION:
        fail(
            f"trace has only {invocation} target invocation(s); "
            f"need invocation {TARGET_INVOCATION}"
        )
    if target_returns != invocation:
        fail(f"saw {invocation} calls but {target_returns} returns")
    if iteration_count <= 1:
        fail(f"non-rich loop count harvested: {iteration_count}")

    question = (
        "Run only the pytest test "
        "`fastapi_qa/routing_populate_api_route_state_s2_loops/files/"
        "testcase.py::TestPopulateApiRouteStateLoop::"
        "test_included_route_response_merge`. During that test run, consider "
        "the second invocation of "
        "`fastapi.routing._populate_api_route_state` in "
        "`fastapi/routing.py`. An invocation means one runtime call of exactly "
        "that dotted function (not a call of a nested comprehension frame), "
        "numbered 1-based in chronological call-entry order. For that "
        f"invocation, how many iterations does the `for` loop whose header "
        f"begins at line {loop_header} execute? Source line numbers are "
        "absolute, 1-based line numbers in the named repository file; for a "
        "multi-line statement, the relevant line is where the statement or "
        "expression begins. Define iteration N (1-based) as the Nth time that "
        f"invocation reaches the loop body's first executable source line, "
        f"line {body_first_line}; the loop-header evaluation itself does not "
        "count as an iteration. Return exactly one JSON object with the key "
        "`loop_iteration_count` and an integer value. There are no ordering, "
        "deduplication, string-formatting, or null-value conventions to apply "
        "to this scalar integer."
    )
    result = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
