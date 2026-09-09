from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/encoders.py"
TARGET_FUNC = "fastapi.encoders.jsonable_encoder"
SELECTED_INVOCATION = 3
EVENT_RE = re.compile(
    r"(?P<file>\S+fastapi/encoders\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test `fastapi_qa/encoders_jsonable_encoder_s1_cfg/files/testcase.py::TestJsonableEncoderControlFlow::test_programmatic_nested_payload_uses_varied_paths`. What is the exact ordered sequence of executed line-event locations in the third invocation of `fastapi.encoders.jsonable_encoder` from `fastapi/encoders.py`, after applying the multi-line normalization rule below?

An invocation is one runtime Python `call` event for exactly `fastapi.encoders.jsonable_encoder`, counted 1-based in chronological order during this test. Recursive calls count as separate invocations at the instant their `call` event occurs. Select invocation 3. Include only Python `line` events emitted while that selected invocation's own frame is active. Exclude its `call`, `return`, and `exception` events; exclude every event in recursively called `jsonable_encoder` frames and in all other functions. Such recursive calls still affect the invocation numbering. Preserve the line events in chronological emission order and preserve every duplicate; do not sort or deduplicate them.

Line numbers are absolute, 1-based source line numbers in `fastapi/encoders.py` as it exists in the repository. Normalize each emitted line number to the starting line (`lineno`) of the smallest enclosing Python statement (`ast.stmt`) in the target function: choose the containing statement with the shortest inclusive `lineno` through `end_lineno` span, breaking ties by the greatest `lineno` and then the smallest `end_lineno`. Thus, every event attributed to a continuation line of a multi-line call, condition, or other statement is reported as the line where that statement begins. The function's `def` line is not included in this sequence. Decorator and docstring lines would appear only if Python emitted line events for them in the selected frame, and any such event is normalized by the same rule.

Return exactly one JSON object with the key `executed_path`. Its value is a JSON array in the chronological order just defined, where every element is exactly `{"file":"fastapi/encoders.py","func":"fastapi.encoders.jsonable_encoder","line":N}` and `N` is the normalized integer line number. The `file` and `func` values use those exact repo-relative and dotted fully-qualified strings in every element; no alternate path or name spelling is allowed. There is no value stringification or `repr()` conversion in this answer: the two string fields are the exact constants shown, and `line` is a JSON integer."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def statement_start_map(source_path: Path) -> dict[int, int]:
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "jsonable_encoder"
    ]
    if len(function_nodes) != 1:
        fail(f"expected one jsonable_encoder definition, found {len(function_nodes)}")

    function_node = function_nodes[0]
    statements = [
        node
        for node in ast.walk(function_node)
        if isinstance(node, ast.stmt)
        and node is not function_node
        and getattr(node, "end_lineno", None) is not None
    ]
    starts: dict[int, int] = {}
    for line_number in range(function_node.lineno, function_node.end_lineno + 1):
        containing = [
            statement
            for statement in statements
            if statement.lineno <= line_number <= statement.end_lineno
        ]
        if containing:
            selected = min(
                containing,
                key=lambda statement: (
                    statement.end_lineno - statement.lineno,
                    -statement.lineno,
                    statement.end_lineno,
                ),
            )
            starts[line_number] = selected.lineno
    return starts


def parse_selected_path(
    trace_path: Path, source_path: Path
) -> tuple[list[dict[str, str | int]], int, int]:
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    starts = statement_start_map(source_path)
    stack: list[dict[str, object]] = []
    invocations: list[dict[str, object]] = []
    target_events = 0
    line_events = 0

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None:
                continue
            normalized_file = match.group("file").replace("\\", "/")
            if not normalized_file.endswith(TARGET_FILE):
                continue
            if match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            event = match.group("event")
            raw_line_number = int(match.group("line"))

            if event == "call":
                invocation = {
                    "number": len(invocations) + 1,
                    "lines": [],
                    "returned": False,
                }
                invocations.append(invocation)
                stack.append(invocation)
            elif event == "line":
                if not stack:
                    fail("encountered a target line event outside an invocation")
                if raw_line_number not in starts:
                    fail(
                        "no enclosing statement for target line event "
                        f"at line {raw_line_number}"
                    )
                lines = stack[-1]["lines"]
                assert isinstance(lines, list)
                lines.append(starts[raw_line_number])
                line_events += 1
            elif event == "return":
                if not stack:
                    fail("encountered a target return event outside an invocation")
                invocation = stack.pop()
                invocation["returned"] = True

    if target_events == 0:
        fail(f"trace log contains zero events for {TARGET_FUNC}")
    if stack:
        fail("trace log ended before all target invocations returned")
    if len(invocations) < SELECTED_INVOCATION:
        fail(
            f"expected invocation {SELECTED_INVOCATION}, found only {len(invocations)}"
        )
    if any(not invocation["returned"] for invocation in invocations):
        fail("at least one target invocation did not return")
    if line_events < 50:
        fail(f"expected at least 50 target line events, found {line_events}")

    selected_lines = invocations[SELECTED_INVOCATION - 1]["lines"]
    assert isinstance(selected_lines, list)
    if len(selected_lines) < 10:
        fail(
            f"selected invocation path is too short: {len(selected_lines)} line events"
        )
    if len(set(selected_lines)) < 12:
        fail(
            "selected invocation did not cover at least 12 distinct normalized lines"
        )

    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line_number}
        for line_number in selected_lines
    ]
    return executed_path, len(invocations), line_events


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    repository_root = Path(__file__).resolve().parents[3]
    executed_path, invocation_count, line_event_count = parse_selected_path(
        arguments.trace_log, repository_root / TARGET_FILE
    )
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    with arguments.out.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True)
        output_file.write("\n")

    print(
        f"Wrote {len(executed_path)} selected line events from "
        f"{invocation_count} invocations ({line_event_count} total line events) "
        f"to {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
