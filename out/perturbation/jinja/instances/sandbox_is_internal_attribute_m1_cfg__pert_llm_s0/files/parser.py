#!/usr/bin/env python3
"""Parse trace logs for is_internal_attribute line execution counts."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/sandbox.py"
TARGET_FUNC = "jinja2.sandbox.is_internal_attribute"
FUNCTION_START_LINE = 115
BODY_START_LINE = 127
BODY_END_LINE = 149

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _function_body_lines(source_path: Path) -> list[int]:
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "is_internal_attribute":
            if node.lineno != FUNCTION_START_LINE:
                raise SystemExit(
                    f"Expected {FUNCTION_START_LINE=} for is_internal_attribute, got {node.lineno}"
                )
            lines: set[int] = set()
            for child in ast.walk(node):
                if not hasattr(child, "lineno"):
                    continue
                start = getattr(child, "lineno", None)
                end = getattr(child, "end_lineno", start)
                if start is None:
                    continue
                if end is None:
                    end = start
                for line in range(start, end + 1):
                    if BODY_START_LINE <= line <= BODY_END_LINE:
                        lines.add(line)
            return sorted(lines)
    raise SystemExit("Could not locate is_internal_attribute in sandbox.py")


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def harvest_line_counts(trace_log: Path, scoped_lines: list[int]) -> dict[int, int]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    counts = {line: 0 for line in scoped_lines}
    target_events = 0

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        if parsed["event"] != "line":
            continue

        lineno = int(parsed["lineno"])
        if lineno in counts:
            counts[lineno] += 1

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    line_events = sum(counts.values())
    if line_events == 0:
        raise SystemExit(
            f"Trace contains {target_events} target events but zero line events "
            f"within scoped body lines {BODY_START_LINE}-{BODY_END_LINE}"
        )

    return counts


def build_question(scoped_lines: list[int]) -> str:
    first_line = scoped_lines[0]
    last_line = scoped_lines[-1]
    return (
        "Consider every test method in "
        "`jinja_qa/sandbox_is_internal_attribute_m1_cfg/files/testcase.py::"
        "TestSandboxInternalAttributePolicy`. The answer aggregates behavior "
        "across **all** `test_*` methods in that class, in the chronological "
        "order pytest collects and runs them (definition order in the file).\n\n"
        "Those tests reach `jinja2.sandbox.is_internal_attribute` in "
        f"`{TARGET_FILE}` only **indirectly**: through "
        "`SandboxedEnvironment.getattr`, `SandboxedEnvironment.getitem`, or "
        "compiled templates that call those sandbox hooks — never by importing "
        "or calling `is_internal_attribute` directly.\n\n"
        "Target function: `jinja2.sandbox.is_internal_attribute` "
        f"(the function beginning at line {FUNCTION_START_LINE} of `{TARGET_FILE}`).\n\n"
        "**Scoped lines** are every physical source line from "
        f"{first_line} through {last_line} inclusive that belongs to the "
        "function's executable body (all statement and continuation lines inside "
        "the `def`, excluding the `def` line itself, the docstring, blank lines, "
        "and comment-only lines). Continuation lines inside parenthesized "
        "expressions are in scope as separate physical lines.\n\n"
        "**Line execution** means one `line` trace event whose file path ends "
        f"with `{TARGET_FILE}`, whose qualified name is exactly `{TARGET_FUNC}`, "
        "and whose line number equals L. Count every such event across the entire "
        "test run using Python's `sys.settrace` line semantics: each physical "
        "line number reported by the interpreter increments that line's total "
        "independently (continuation lines inside a multi-line call may each "
        "produce their own event). Multiple invocations of the function sum "
        "together. The `def` line, decorator lines, and docstring lines are out "
        "of scope and never appear in the answer. `call`, `return`, and "
        "`exception` events do not contribute to these counts.\n\n"
        "For each scoped line L, report the total number of times line L "
        "executed. Lines that never executed must appear with count `0`.\n\n"
        "Return JSON with the single top-level key `line_execution_counts`: a "
        "list of objects, each with keys `line` (absolute 1-based line number "
        f"in `{TARGET_FILE}`) and `count` (non-negative integer). Sort the list "
        "by `line` ascending; when line numbers tie (they cannot), break ties "
        f"by `count` ascending."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    scoped_lines = _function_body_lines(_repo_root() / TARGET_FILE)
    counts = harvest_line_counts(args.trace_log, scoped_lines)

    oracle_answer = {
        "line_execution_counts": [
            {"line": line, "count": counts[line]} for line in sorted(scoped_lines)
        ]
    }
    template_answer = {"line_execution_counts": [{"count": "int", "line": "int"}]}

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": build_question(scoped_lines),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
