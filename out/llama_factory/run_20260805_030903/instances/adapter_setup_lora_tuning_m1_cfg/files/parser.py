from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/llamafactory/model/adapter.py"
TARGET_FUNC = "llamafactory.model.adapter._setup_lora_tuning"
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test `llama_factory_qa/adapter_setup_lora_tuning_m1_cfg/files/testcase.py::TestAdapterSetupControlFlow::test_seeded_indirect_adapter_scenarios` and report the source lines covered by all invocations of `llamafactory.model.adapter._setup_lora_tuning` in `src/llamafactory/model/adapter.py` during that test.

An invocation is one entry into exactly that function, equivalent to one Python `call` event for its frame, counted 1-based in chronological order. Consider every invocation made during this single test run. A line is covered when a Python runtime `line` event occurs in the target function's own frame after an invocation's entry and before that frame returns or exits by exception. Exclude `call`, `return`, and `exception` events, events from callers and callees, and events from every other function or file.

Line numbers are absolute, 1-based source line numbers in the named repository file as it exists for the test run. For a physical continuation line in a multi-line statement or expression, normalize the event to the first line of its innermost enclosing AST statement; for example, a continuation event belonging to an assignment whose statement starts on line 7 is reported as 7. The function's `def` line, decorator lines, and docstring lines are excluded because they are not runtime `line` events in the function body.

Return exactly one JSON object with shape `{"covered_lines": ["int"]}`. `covered_lines` is a JSON array of integer line numbers. Take the union across all target invocations, remove duplicate normalized line numbers, and sort the integers in strictly ascending numeric order. Do not report file names, function names, invocation numbers, counts, or any other keys."""


def statement_start_lines(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_setup_lora_tuning"
        ),
        None,
    )
    if target is None or target.end_lineno is None:
        raise RuntimeError(f"target function not found in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and node.end_lineno is not None
    ]
    mapping: dict[int, int] = {}
    for line in range(target.lineno + 1, target.end_lineno + 1):
        enclosing = [node for node in statements if node.lineno <= line <= node.end_lineno]
        if enclosing:
            innermost = min(enclosing, key=lambda node: (node.end_lineno - node.lineno, -node.lineno))
            mapping[line] = innermost.lineno
        else:
            mapping[line] = line
    return mapping


def parse_trace(trace_path: Path, source_path: Path) -> dict[str, list[int]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events: list[tuple[str, int]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        target_events.append((match.group("event"), int(match.group("line"))))

    if not target_events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")

    call_count = sum(event == "call" for event, _line in target_events)
    if call_count < 3:
        raise RuntimeError(f"trace contains only {call_count} target invocations; at least 3 are required")

    starts = statement_start_lines(source_path)
    covered = sorted(
        {
            starts.get(line, line)
            for event, line in target_events
            if event == "line"
        }
    )
    if not covered:
        raise RuntimeError(f"trace contains zero line events for {TARGET_FUNC}")
    return {"covered_lines": covered}


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    source_path = root_dir / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": parse_trace(args.trace_log, source_path),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(payload['oracle_answer']['covered_lines'])} covered lines to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
