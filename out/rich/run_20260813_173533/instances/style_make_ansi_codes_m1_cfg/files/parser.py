#!/usr/bin/env python3
"""Parse a trace log into an M1_IntraProceduralCFG oracle for _make_ansi_codes."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "M1_IntraProceduralCFG"
TARGET_FILE = "rich/style.py"
TARGET_FUNC = "rich.style.Style._make_ansi_codes"
TEST_MODULE = "rich_qa/style_make_ansi_codes_m1_cfg/files/testcase.py"
TEST_CLASS = "StyleMakeAnsiCodesM1CfgTest"

QUESTION = f"""\
During pytest run {TEST_MODULE}::{TEST_CLASS}, consider every test method defined on that class. The answer aggregates execution across ALL test methods in the class, in the order pytest collects them (alphabetical order of test method names on the class).

Target function: {TARGET_FUNC} defined in {TARGET_FILE} (the def statement is on line 344).

Count how many times each physical source line inside the function body executes as a line trace event during the entire test run described above. Sum counts across every invocation of {TARGET_FUNC} in every test method; do not reset between methods.

An invocation is one call event for {TARGET_FUNC}. Only event=line records count toward line execution totals. Include line events only from frames whose func equals {TARGET_FUNC} (module-qualified format: package.module.Class.method, e.g. rich.style.Style.render). Ignore call, return, and exception events when counting line executions. Do not count line events from callees such as Color.downgrade or list.append even when triggered from this function.

Scope is every line from the first statement of the function body through the final return statement, inclusive, as defined in {TARGET_FILE} at the def on line 344. That range is lines 354 through 385. The def line (344), decorator lines, and docstring lines (345-352) are outside scope and must not appear. Blank lines and comment-only lines inside the body range are in scope and must be reported with count 0 if never executed. For a multi-line statement, Python emits the line event on the line where that statement begins; for example, the background-color extend call beginning on line 379 reports line 379 when execution enters that statement, not on continuation lines 380-382.

Report the answer as JSON with top-level key line_execution_counts whose value is a list of objects sorted by line ascending (numeric ascending; ties impossible). Each object has exactly these keys:
- line (int): 1-based physical line number in {TARGET_FILE}
- count (int): total number of line events for that line across the whole test run

Every line in scope (354-385) must appear exactly once. Lines that never execute must have count 0.\
"""

TEMPLATE_ANSWER = {
    "line_execution_counts": [
        {"count": "int", "line": "int"},
    ],
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

BODY_START = 354
BODY_END = 385


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _body_lines_from_source(source_path: Path) -> list[int]:
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Style":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_make_ansi_codes":
                    stmts = item.body
                    if (
                        stmts
                        and isinstance(stmts[0], ast.Expr)
                        and isinstance(stmts[0].value, ast.Constant)
                        and isinstance(stmts[0].value.value, str)
                    ):
                        stmts = stmts[1:]
                    if not stmts or stmts[0].lineno != BODY_START or stmts[-1].lineno != BODY_END:
                        raise SystemExit(
                            f"unexpected executable body span for _make_ansi_codes: "
                            f"{stmts[0].lineno if stmts else '?'}-{stmts[-1].lineno if stmts else '?'}"
                        )
                    return list(range(BODY_START, BODY_END + 1))
    raise SystemExit(f"could not locate _make_ansi_codes body in {TARGET_FILE}")


def _parse_line_counts(trace_log: Path) -> dict[int, int]:
    if not trace_log.is_file():
        raise SystemExit(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_log}")

    counts: dict[int, int] = {}
    matched_events = 0

    for raw_line in text.splitlines():
        match = TRACE_LINE_RE.match(raw_line)
        if not match:
            continue

        if _normalize_file(match.group("file")) != TARGET_FILE:
            continue

        if match.group("func") != TARGET_FUNC:
            continue

        matched_events += 1
        if match.group("event") != "line":
            continue

        line_no = int(match.group("line"))
        if BODY_START <= line_no <= BODY_END:
            counts[line_no] = counts.get(line_no, 0) + 1

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    return counts


def _build_answer(counts: dict[int, int], scope_lines: list[int]) -> dict:
    line_execution_counts = [
        {"line": line_no, "count": counts.get(line_no, 0)} for line_no in scope_lines
    ]
    if not any(entry["count"] > 0 for entry in line_execution_counts):
        raise SystemExit("no executed lines found in scope for target function")

    return {"line_execution_counts": line_execution_counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    scope_lines = _body_lines_from_source(_repo_root() / TARGET_FILE)
    counts = _parse_line_counts(args.trace_log)
    oracle_answer = _build_answer(counts, scope_lines)

    payload = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
