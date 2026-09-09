import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/optimize_joins.py"
TARGET_FUNC = "sqlglot.optimizer.optimize_joins.optimize_joins"
LOOP_HEADER_LINE = 54
EXPECTED_INVOCATIONS = 12

QUESTION = (
    "Run every test method collected from "
    "`sqlglot_qa/optimize_joins_optimize_joins_m2_loops/files/testcase.py::"
    "TestOptimizeJoinsLoopDynamics` and aggregate over all of those methods. In "
    "`sqlglot.optimizer.optimize_joins.optimize_joins` in "
    "`sqlglot/optimizer/optimize_joins.py`, consider the `for predicate in "
    "on.flatten():` loop whose header is line 54. For each invocation, count that "
    "loop's iterations across the entire invocation, including all entries caused "
    "by its enclosing loops and all Select nodes: iteration N is the Nth execution "
    "of the loop body's first statement, the `if` beginning on line 55. An "
    "invocation is one call of exactly this target function (not a callee or another "
    "same-named function), numbered 1-based in chronological execution order across "
    "the pytest run. An invocation in which line 55 never executes has count zero. "
    "Report the largest and smallest per-invocation counts; repeated counts are "
    "retained when determining the extrema, and no sorting or deduplication changes "
    "the scalar results. Line numbers are absolute 1-based source line numbers in "
    "the named repository file as it exists for this run. For a multi-line "
    "statement, an execution belongs to the line on which that statement begins; "
    "the function's `def` line, docstring lines, loop-header executions, return "
    "events, and executions in other frames do not count as iterations. Return "
    "exactly a JSON object with keys `max_iterations` and `min_iterations`, each a "
    "JSON decimal integer (not a string), in that key order."
)

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def loop_body_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "optimize_joins"
        ),
        None,
    )
    if function is None:
        raise RuntimeError(f"target function not found in {source_path}")

    loop = next(
        (
            node
            for node in ast.walk(function)
            if isinstance(node, (ast.For, ast.AsyncFor)) and node.lineno == LOOP_HEADER_LINE
        ),
        None,
    )
    if loop is None or not loop.body:
        raise RuntimeError(
            f"loop at absolute line {LOOP_HEADER_LINE} not found in target function"
        )
    return loop.body[0].lineno


def parse_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    counts: list[int] = []
    current_count: int | None = None
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            if current_count is not None:
                raise RuntimeError("nested or unterminated target invocation in trace")
            current_count = 0
        elif event == "line" and line == body_line:
            if current_count is None:
                raise RuntimeError("iteration event appeared outside a target invocation")
            current_count += 1
        elif event == "return":
            if current_count is None:
                raise RuntimeError("return event appeared outside a target invocation")
            counts.append(current_count)
            current_count = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if current_count is not None:
        raise RuntimeError("trace ended during a target invocation")
    if len(counts) != EXPECTED_INVOCATIONS:
        raise RuntimeError(
            f"expected {EXPECTED_INVOCATIONS} completed invocations, found {len(counts)}"
        )
    return counts


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    body_line = loop_body_line(source_path)
    counts = parse_counts(args.trace_log, body_line)
    answer = {
        "max_iterations": max(counts),
        "min_iterations": min(counts),
    }
    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
