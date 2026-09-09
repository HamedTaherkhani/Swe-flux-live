from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/utils/misc.py"
TARGET_FUNC = "scrapy.utils.misc.is_generator_with_return_value"
LOOP_HEADER_LINE = 287

QUESTION = (
    "Run every test method collected from the pytest class node "
    "`scrapy_qa/misc_is_generator_with_return_value_m2_loops/files/testcase.py::"
    "GeneratorReturnLoopTest` (that is, aggregate over all `test_...` methods in "
    "that class, in pytest's collection order). Consider every invocation of "
    "`scrapy.utils.misc.is_generator_with_return_value` in `scrapy/utils/misc.py` "
    "during those test methods. An invocation is one call of that exact function, "
    "numbered 1-based in chronological call order across the complete class run. "
    "For the `for` loop whose header begins at line 287, compute each invocation's "
    "iteration count, then report the maximum and minimum of those counts across "
    "all invocations. Define iteration N (1-based within an invocation) as the Nth "
    "execution of the loop body's first statement, the `if` statement beginning "
    "at line 288. Repeated executions count separately and are never deduplicated; "
    "an invocation that never executes line 288 has an iteration count of zero. "
    "Evaluations of the iterable or loop machinery that do not enter the body do "
    "not count. Line numbers are absolute, 1-based source line numbers in the named "
    "repository file as it exists for this run; for a multi-line statement, its "
    "line is where that statement or expression begins. The function's `def` line, "
    "decorator lines, and docstring lines are not loop iterations. Include every "
    "invocation, including any invocation that returns before reaching the loop; "
    "do not sort or deduplicate invocations before taking the extrema. Return "
    "exactly one JSON object with exactly the keys `max_iterations` and "
    "`min_iterations`, in that key order. Both values are raw JSON integers, not "
    "quoted strings; no value formatting with `repr` or `str` and no null/empty "
    "sentinel is used."
)

TRACE_RE = re.compile(
    r"\s(?P<file>\S*scrapy/utils/misc\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def find_loop_body_line(source_path: Path) -> int:
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        raise SystemExit(f"ERROR: cannot parse target source {source_path}: {exc}") from exc

    targets = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "is_generator_with_return_value"
    ]
    if len(targets) != 1:
        raise SystemExit(
            f"ERROR: expected one target function in {source_path}, found {len(targets)}"
        )

    loops = [
        node
        for node in ast.walk(targets[0])
        if isinstance(node, ast.For) and node.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1 or not loops[0].body:
        raise SystemExit(
            f"ERROR: expected one for loop at {TARGET_FILE}:{LOOP_HEADER_LINE}"
        )
    return loops[0].body[0].lineno


def iteration_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.exists():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        raise SystemExit(f"ERROR: trace contains zero events for {TARGET_FUNC}")

    counts: list[int] = []
    active_count: int | None = None
    for line_number, event in events:
        if event == "call":
            if active_count is not None:
                raise SystemExit(
                    f"ERROR: overlapping invocations found for non-recursive {TARGET_FUNC}"
                )
            active_count = 0
        elif active_count is not None and event == "line" and line_number == body_line:
            active_count += 1
        elif active_count is not None and event == "return":
            counts.append(active_count)
            active_count = None

    if active_count is not None:
        raise SystemExit(f"ERROR: final invocation of {TARGET_FUNC} has no return event")
    if not counts:
        raise SystemExit(f"ERROR: no completed invocations found for {TARGET_FUNC}")
    return counts


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    body_line = find_loop_body_line(Path(TARGET_FILE))
    if body_line != 288:
        raise SystemExit(
            f"ERROR: expected loop body at {TARGET_FILE}:288, found {body_line}"
        )

    counts = iteration_counts(args.trace_log, body_line)
    answer = {
        "max_iterations": max(counts),
        "min_iterations": min(counts),
    }
    payload = {
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
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
