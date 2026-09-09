#!/usr/bin/env python3
"""Parse trace logs for nodes_dump_m2_loops (M2_Loops max/min inner-loop iterations)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TARGET_FILE = "src/jinja2/nodes.py"
TARGET_FUNC = "jinja2.nodes.Node.dump.<locals>._dump"
LOOP_HEADER_LINE = 268
LOOP_BODY_FIRST_LINE = 269
LOOP_END_LINE = 272

TEST_CLASS = "NodesDumpM2LoopsTest"
TEST_FILE = "jinja_qa/nodes_dump_m2_loops/files/testcase.py"

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
)


@dataclass
class _FrameState:
    active_inner_loop: bool = False
    current_inner_count: int = 0
    completed_inner_counts: list[int] = field(default_factory=list)

    def start_inner_loop(self) -> None:
        if not self.active_inner_loop:
            self.active_inner_loop = True
            self.current_inner_count = 0

    def increment_inner_loop(self) -> None:
        if self.active_inner_loop:
            self.current_inner_count += 1

    def finish_inner_loop(self) -> None:
        if self.active_inner_loop:
            self.completed_inner_counts.append(self.current_inner_count)
            self.active_inner_loop = False
            self.current_inner_count = 0

    def finalize(self) -> list[int]:
        if self.active_inner_loop:
            self.completed_inner_counts.append(self.current_inner_count)
            self.active_inner_loop = False
            self.current_inner_count = 0
        return self.completed_inner_counts


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if TARGET_FILE in normalized:
        return TARGET_FILE
    return normalized


def _discover_test_method_ids(testcase_path: Path) -> list[str]:
    source = testcase_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(testcase_path))
    method_names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TEST_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    method_names.append(item.name)
    method_names.sort()
    if not method_names:
        _fail(f"no test methods found in class {TEST_CLASS}")
    return [
        f"{TEST_FILE}::{TEST_CLASS}::{method_name}" for method_name in method_names
    ]


def _parse_trace_line(raw_line: str) -> dict[str, str | int] | None:
    if raw_line.startswith("[TRACE]"):
        return None
    match = TRACE_LINE_RE.match(raw_line.strip())
    if not match:
        return None
    return {
        "file": _normalize_file(match.group("file")),
        "lineno": int(match.group("lineno")),
        "func": match.group("func"),
        "event": match.group("event"),
    }


def _load_target_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["file"] == TARGET_FILE and parsed["func"] == TARGET_FUNC:
            events.append(parsed)

    if not events:
        _fail(
            f"no trace events for {TARGET_FUNC} in {TARGET_FILE}; "
            f"check TRACE_FILE/TRACE_FUNC configuration"
        )
    return events


def _compute_inner_loop_iteration_counts(events: list[dict[str, str | int]]) -> list[int]:
    frame_stack: list[_FrameState] = []
    all_counts: list[int] = []

    for event in events:
        kind = str(event["event"])
        lineno = int(event["lineno"])

        if kind == "call":
            frame_stack.append(_FrameState())
            continue

        if kind in ("return", "exception"):
            if not frame_stack:
                continue
            frame = frame_stack.pop()
            all_counts.extend(frame.finalize())
            continue

        if kind != "line" or not frame_stack:
            continue

        frame = frame_stack[-1]
        if lineno == LOOP_HEADER_LINE:
            frame.start_inner_loop()
        elif lineno == LOOP_BODY_FIRST_LINE:
            frame.increment_inner_loop()
        elif lineno == LOOP_END_LINE:
            frame.finish_inner_loop()

    if frame_stack:
        _fail("trace ended with unclosed _dump frames")

    if not all_counts:
        _fail(
            f"no completed inner-loop executions detected at {TARGET_FILE}:"
            f"{LOOP_HEADER_LINE}"
        )

    return all_counts


def _build_question(test_method_ids: list[str]) -> str:
    method_list = "; ".join(f"`{method_id}`" for method_id in test_method_ids)
    return (
        f"Consider the pytest test class `{TEST_FILE}::{TEST_CLASS}` "
        f"(class `{TEST_CLASS}` in `{TEST_FILE}`). The answer aggregates behavior "
        f"across ALL test methods in that class, executed in pytest default "
        f"collection order (alphabetical by test method name). The covered "
        f"pytest ids are: {method_list}. "
        f"During that combined run, the nested function `{TARGET_FUNC}` in "
        f"`{TARGET_FILE}` executes whenever `jinja2.nodes.Node.dump` serializes "
        f"an AST node; the test reaches it only indirectly by parsing templates "
        f"with `jinja2.Environment.parse` and calling `.dump()` on the resulting "
        f"node tree (the test never names `_dump`). "
        f"An invocation of `{TARGET_FUNC}` is one `call` event for that function "
        f"during the combined test run, counted in chronological order starting at 1. "
        f"Consider the `for` loop whose header begins on line {LOOP_HEADER_LINE} of "
        f"`{TARGET_FILE}` (the loop `for idx, item in enumerate(value):` inside the "
        f"list-serialization branch). A loop activation is one complete execution of "
        f"that `for` statement for a single list-valued field during some invocation of "
        f"`{TARGET_FUNC}`: it begins when line {LOOP_HEADER_LINE} executes while not "
        f"already inside that same activation, and ends when line {LOOP_END_LINE} "
        f"(`buf.append(\"]\")`) executes for that activation. Because Python re-executes "
        f"the `for` header line on every iteration, repeated line-{LOOP_HEADER_LINE} "
        f"events before the matching line-{LOOP_END_LINE} belong to the same activation "
        f"and must not be counted as separate activations. Activations are numbered in "
        f"chronological trace order across the whole combined run. "
        f"For each activation, define iteration counting as 1-based: iteration N is "
        f"the Nth time line {LOOP_BODY_FIRST_LINE} (`if idx:`), the loop body's first "
        f"line, executes during that activation. Count an iteration even when the "
        f"`if idx:` test is false (including the first iteration where `idx` is 0). "
        f"If the enumerated list is empty, the activation performs 0 iterations. "
        f"Line numbers are absolute, 1-based, and refer to `{TARGET_FILE}` as it "
        f"exists in the repository; for multi-line statements, attribute executed-line "
        f"events to the line where that statement begins. Decorator lines, the "
        f"`def dump` line, the nested `def _dump` line, and docstring lines are never "
        f"executed and must not be counted. "
        f"Across all loop activations during the combined run, report the maximum and "
        f"minimum iteration counts observed. "
        f"Report the answer as a JSON object with exactly these keys: "
        f"`max_iterations` (JSON number, the largest iteration count among activations) "
        f"and `min_iterations` (JSON number, the smallest iteration count among "
        f"activations). Use bare integers, not quoted strings."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    testcase_path = Path(__file__).resolve().parent / "testcase.py"
    test_method_ids = _discover_test_method_ids(testcase_path)

    events = _load_target_events(args.trace_log)
    iteration_counts = _compute_inner_loop_iteration_counts(events)

    oracle_answer = {
        "max_iterations": max(iteration_counts),
        "min_iterations": min(iteration_counts),
    }
    payload = {
        "question_kind": "M2_Loops",
        "question": _build_question(test_method_ids),
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
