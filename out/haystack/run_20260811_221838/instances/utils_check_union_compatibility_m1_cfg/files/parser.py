#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/core/super_component/utils.py"
TARGET_FUNC = "_check_union_compatibility"
TARGET_QUALNAME = "haystack.core.super_component.utils._check_union_compatibility"

QUESTION = """Run every test method in the unittest class `TestUnionCompatibilityCFG` defined in `haystack_qa/utils_check_union_compatibility_m1_cfg/files/testcase.py`. This means all pytest items whose IDs have the form `haystack_qa/utils_check_union_compatibility_m1_cfg/files/testcase.py::TestUnionCompatibilityCFG::test_*`; aggregate the counts over all of those methods, with each method included exactly once.

For `haystack.core.super_component.utils._check_union_compatibility`, defined in `haystack/core/super_component/utils.py` at line 62, report the total number of runtime line events for every physical line in the function body. The body scope is the inclusive range from the first AST body statement (the docstring) through the function's AST `end_lineno`; the `def` line and any decorator lines are excluded. Include every 1-based physical source line in that inclusive range, including docstring, blank, comment-only, and continuation lines. A line in scope that produces no line event must be reported with count 0.

An executed line means one CPython `sys.settrace` `line` event from a frame whose code file is exactly the named repository file and whose exact function name is `haystack.core.super_component.utils._check_union_compatibility`; events from every other file or function are excluded. `call`, `return`, and `exception` events do not increment line counts. Each occurrence increments the count, so repeated loop-condition and loop-body events across invocations are all counted; do not deduplicate events. An invocation is one `call` event for this exact function during any covered test method, although invocation events themselves are not part of the answer. For a multi-line statement or expression, use the 1-based physical starting line supplied as the event frame's `f_lineno`; do not copy that event to continuation lines, which remain 0 unless they independently receive a line event.

Return exactly one JSON object with key `line_execution_counts`. Its value is a list containing one object per physical line in the body scope. Each object has exactly the integer keys/values shape `{"count": <int>, "line": <int>}` (the JSON object keys are strings), and the list is sorted by `line` in strictly ascending order. Counts are decimal JSON integers, never strings or null. There is no secondary tie-breaker because each line appears exactly once."""


def _function_body_range(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read target source {source_path}: {exc}") from exc

    tree = ast.parse(source, filename=str(source_path))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_FUNC
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {TARGET_FUNC} definition, found {len(matches)}")

    function = matches[0]
    if not function.body or function.end_lineno is None:
        raise RuntimeError(f"target function {TARGET_FUNC} has no usable body range")
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
        rf"{re.escape(TARGET_QUALNAME)}\s+event=(?P<event>\w+)\b"
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
    source_path = Path.cwd() / TARGET_FILE
    start_line, end_line = _function_body_range(source_path)

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
