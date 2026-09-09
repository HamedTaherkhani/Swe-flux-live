#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/components/builders/chat_prompt_builder.py"
TARGET_CLASS = "ChatPromptBuilder"
TARGET_FUNC = "run"
TARGET_QUALNAME = "haystack.components.builders.chat_prompt_builder.ChatPromptBuilder.run"
TARGET_TRACE_NAME = "haystack.components.builders.chat_prompt_builder.run"

QUESTION = """Run every test method in the unittest class `TestChatPromptBuilderRunCFG` defined in `haystack_qa/chat_prompt_builder_run_m1_cfg/files/testcase.py`. The covered pytest items are exactly those whose IDs have the form `haystack_qa/chat_prompt_builder_run_m1_cfg/files/testcase.py::TestChatPromptBuilderRunCFG::test_*`; include every such method exactly once and aggregate counts over all of them. Method execution order does not affect the requested totals.

For `haystack.components.builders.chat_prompt_builder.ChatPromptBuilder.run`, defined in `haystack/components/builders/chat_prompt_builder.py` at line 209, report the total number of runtime line events for every physical line in the function body across all invocations made by all covered test methods. The body scope is the inclusive range from the first AST body statement (the docstring) through the function AST node's `end_lineno`. The decorator, the `def` line, and all parameter-signature lines are excluded. Include every 1-based physical source line in that inclusive body range, including docstring, blank, comment-only, and continuation lines; any in-scope line that produces no line event must appear with count 0.

A counted event is one CPython runtime `line` event whose frame's code file is exactly the named repository file and whose frame code object is the code object of the named `ChatPromptBuilder.run` definition (its code name is exactly `run`). Events from other functions named `run`, nested comprehension or generator frames, and all other files are excluded. `call`, `return`, and `exception` events do not increment line counts. Each line-event occurrence increments its line's count: repeated events from loop conditions, loop bodies, branches, and separate invocations are not deduplicated. An invocation means one runtime `call` event for this exact function during a covered test method; invocations are conceptually numbered 1-based in chronological execution order, although invocation numbers are not emitted. For a multi-line statement or expression, count the event only for the 1-based physical source line reported by the executing frame as `f_lineno`; do not copy it to other lines. A continuation line remains at 0 unless CPython independently reports a line event for that physical line.

Return exactly one JSON object with the key `line_execution_counts`. Its value is a list with one object for every physical line in the body scope. Each object has exactly the shape `{"count": <int>, "line": <int>}`: both values are decimal JSON integers, never strings or null, and JSON object keys are strings. Sort the list by `line` in strictly ascending numeric order. Each line appears exactly once, so there is no secondary tie-breaker."""


def _function_body_range(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read target source {source_path}: {exc}") from exc

    tree = ast.parse(source, filename=str(source_path))
    classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS
    ]
    if len(classes) != 1:
        raise RuntimeError(f"expected one {TARGET_CLASS} class, found {len(classes)}")

    functions = [
        node
        for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_FUNC
    ]
    if len(functions) != 1:
        raise RuntimeError(
            f"expected one {TARGET_CLASS}.{TARGET_FUNC} definition, found {len(functions)}"
        )

    function = functions[0]
    if not function.body or function.end_lineno is None:
        raise RuntimeError(f"target function {TARGET_CLASS}.{TARGET_FUNC} has no usable body range")
    return function.body[0].lineno, function.end_lineno


def _parse_counts(trace_path):
    try:
        text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read trace log {trace_path}: {exc}") from exc
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        rf"\s(?P<file>\S*{re.escape(TARGET_FILE)}):(?P<line>\d+)\s+"
        rf"{re.escape(TARGET_TRACE_NAME)}\s+event=(?P<event>\w+)\b"
    )
    target_events = []
    counts = Counter()
    for raw_line in text.splitlines():
        match = event_pattern.search(raw_line)
        if match is None:
            continue
        target_events.append(match.group("event"))
        if match.group("event") == "line":
            counts[int(match.group("line"))] += 1

    if not target_events:
        raise RuntimeError(f"trace log contains zero events for {TARGET_QUALNAME}")
    if not counts:
        raise RuntimeError(f"trace log contains zero line events for {TARGET_QUALNAME}")
    return counts


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    counts = _parse_counts(args.trace_log)
    start_line, end_line = _function_body_range(Path.cwd() / TARGET_FILE)
    outside = sorted(line for line in counts if line < start_line or line > end_line)
    if outside:
        raise RuntimeError(f"target line events outside AST body range: {outside}")

    answer = {
        "line_execution_counts": [
            {"count": counts.get(line, 0), "line": line}
            for line in range(start_line, end_line + 1)
        ]
    }
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"line_execution_counts": [{"count": "int", "line": "int"}]},
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
