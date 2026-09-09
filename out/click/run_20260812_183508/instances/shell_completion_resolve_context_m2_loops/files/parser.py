from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/shell_completion.py"
TARGET_FUNC = "click.shell_completion._resolve_context"

QUESTION = """Run all test methods whose names start with `test_` in the unittest class `ResolveContextLoopScenarios` from `click_qa/shell_completion_resolve_context_m2_loops/files/testcase.py` together in one pytest run, and aggregate over every invocation of `click.shell_completion._resolve_context` in `src/click/shell_completion.py` made during those methods. Identify each covered test by the pytest id `click_qa/shell_completion_resolve_context_m2_loops/files/testcase.py::ResolveContextLoopScenarios::<method-name>`, and order the methods lexicographically by method name, which is the collection order for this unittest class.

For the `while args:` loop whose header begins on line 732, report the maximum and minimum iteration count among all invocations. Source line numbers are absolute, 1-based physical line numbers in the named repository file. An invocation is one runtime call entry into the target function; number invocations 1-based in chronological execution order across the complete pytest run. Retain every invocation, including invocations with equal counts; do not deduplicate before taking the extrema.

For this loop, one iteration is one execution of its first body statement, the `name, cmd, args = ...` statement beginning on line 733, in that same target frame. Thus an invocation that never executes line 733 has an iteration count of zero, and an execution of line 733 still counts if that iteration subsequently returns because command resolution produced no command. Count no line executions in callers, callees, or other target invocations toward a given invocation. For a multi-line statement, its relevant executed line is the physical line on which that statement or expression begins; decorator, `def`, and docstring lines do not count as loop iterations.

Return exactly one JSON object with keys `max_iterations` and `min_iterations`, each mapped to a JSON integer. Use no string conversion, null sentinel, sorting, or additional fields."""


def _loop_body_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_resolve_context"
    )
    loops = [node for node in ast.walk(target) if isinstance(node, ast.While)]
    nested = [node for node in loops if node.lineno == 732]
    if len(nested) != 1 or not nested[0].body:
        raise RuntimeError("expected exactly one target while loop at line 732")
    return nested[0].body[0].lineno


def _parse_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_re = re.compile(
        r" (?P<file>\S*src/click/shell_completion\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    counts: list[int] = []
    active: int | None = None
    target_events = 0

    for raw_line in text.splitlines():
        match = event_re.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            if active is not None:
                raise RuntimeError("overlapping target invocations are not supported")
            counts.append(0)
            active = len(counts) - 1
        elif event == "line" and line == body_line:
            if active is None:
                raise RuntimeError("target loop line appeared outside an invocation")
            counts[active] += 1
        elif event == "return":
            if active is None:
                raise RuntimeError("target return appeared outside an invocation")
            active = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not counts:
        raise RuntimeError(f"trace contains no call events for {TARGET_FUNC}")
    if active is not None:
        raise RuntimeError("trace ended before the final target invocation returned")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    try:
        source_path = Path.cwd() / TARGET_FILE
        body_line = _loop_body_line(source_path)
        counts = _parse_counts(args.trace_log, body_line)
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
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(document, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: failed to build loop oracle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
