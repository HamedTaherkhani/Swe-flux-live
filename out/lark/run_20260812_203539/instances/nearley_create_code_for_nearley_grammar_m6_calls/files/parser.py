#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


MODULE = "lark.tools.nearley"
REPO_FILE = "lark/tools/nearley.py"
TARGET = "lark.tools.nearley.create_code_for_nearley_grammar"
EVENT_RE = re.compile(
    r"\s(?P<path>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run every pytest-collected test method whose name begins with `test_` in class `TestNearleyCodeGenerationDynamics` from `lark_qa/nearley_create_code_for_nearley_grammar_m6_calls/files/testcase.py` exactly once, as selected by the pytest class id `lark_qa/nearley_create_code_for_nearley_grammar_m6_calls/files/testcase.py::TestNearleyCodeGenerationDynamics`. Aggregate events across all test methods in that class into one answer; counts are not reported separately by method. The primary target is `lark.tools.nearley.create_code_for_nearley_grammar`, defined in `lark/tools/nearley.py`.

Report invocation counts for this location-defined scope: every module-level function defined directly in `lark/tools/nearley.py`, plus every method defined directly in the body of every class defined directly in that file. Include directly defined `__init__` and other dunder methods, static methods, and class methods. Exclude inherited methods, property getter/setter/deleter functions, nested functions, closures, lambdas, comprehension frames, class-body execution frames, and methods of nested classes. Every definition in this scope must be reported, including definitions that never execute.

Function identity is the dotted runtime module name followed by the definition's qualified name, with no `<locals>` rewriting. For example, a hypothetical method in another module would be `sample_pkg.mod.Widget.run`. The `file` value is the repo-relative POSIX path of the defining source file, which is `lark/tools/nearley.py` for every record in this answer.

One invocation is one Python `call` event for that function's frame during the selected test-class run. Count calls from any frame, including direct, transitive, and recursive calls. Do not count line, return, or exception events. A generator or coroutine produces another `call` event whenever its suspended frame resumes, and each such event counts as another invocation, including a final resumption that completes the frame. Repeated call events are counted independently and are not deduplicated.

Return a JSON object with exactly one key, `invocation_counts`. Its value is a JSON list with exactly one object per in-scope definition. Each object has exactly the keys `count` (JSON integer), `file` (JSON string), and `func` (JSON string). A function with no qualifying call event appears with `count: 0`; do not represent a missing invocation count with JSON null and do not omit the definition. Sort records by `func` ascending in ordinary Unicode code-point order, using `file` ascending as the tie-breaker. Apply no other normalization, formatting, aggregation, or deduplication to names or definition records."""


def fail(message):
    print("ERROR: " + message, file=sys.stderr)
    raise SystemExit(1)


def scope_functions(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    names = []
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, function_nodes):
            names.append(f"{MODULE}.{node.name}")
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if not isinstance(child, function_nodes):
                    continue
                is_property = any(
                    (
                        isinstance(decorator, ast.Name)
                        and decorator.id == "property"
                    )
                    or (
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr in {"getter", "setter", "deleter"}
                    )
                    for decorator in child.decorator_list
                )
                if not is_property:
                    names.append(f"{MODULE}.{node.name}.{child.name}")

    if not names:
        fail(f"no in-scope definitions found in {source_path}")
    if len(names) != len(set(names)):
        fail("duplicate dotted function identities found in target scope")
    return names


def parse_counts(trace_path, scope):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read trace log {trace_path}: {exc}")
    if not lines:
        fail(f"trace log is empty: {trace_path}")

    scope_set = set(scope)
    counts = Counter()
    parsed_events = 0
    target_events = 0
    for line in lines:
        match = EVENT_RE.search(line)
        if not match:
            continue
        parsed_events += 1
        path = match.group("path").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if func == TARGET:
            target_events += 1
        if (
            event == "call"
            and func in scope_set
            and path.endswith("/" + REPO_FILE)
        ):
            counts[func] += 1

    if parsed_events == 0:
        fail("trace log contains no parseable events")
    if target_events == 0:
        fail(f"trace log contains zero events for target function {TARGET}")
    if counts[TARGET] == 0:
        fail(f"trace log contains zero call events for target function {TARGET}")
    return counts


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    scope = scope_functions(Path.cwd() / REPO_FILE)
    counts = parse_counts(Path(args.trace_log), scope)
    records = [
        {"count": counts[func], "file": REPO_FILE, "func": func}
        for func in scope
    ]
    records.sort(key=lambda item: (item["func"], item["file"]))

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [
                {"count": "int", "file": "str", "func": "str"}
            ]
        },
        "oracle_answer": {"invocation_counts": records},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {output_path}")


if __name__ == "__main__":
    main()
