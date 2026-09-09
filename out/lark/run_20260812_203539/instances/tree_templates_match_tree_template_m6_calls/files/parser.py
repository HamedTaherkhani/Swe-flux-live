#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


MODULE = "lark.tree_templates"
REPO_FILE = "lark/tree_templates.py"
TARGET = "lark.tree_templates.TemplateConf._match_tree_template"
EVENT_RE = re.compile(
    r"\s(?P<path>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run every pytest-collected test method whose name begins with `test_` in class `TestTemplateSearchDynamics` from `lark_qa/tree_templates_match_tree_template_m6_calls/files/testcase.py`, exactly once, as selected by the pytest class id `lark_qa/tree_templates_match_tree_template_m6_calls/files/testcase.py::TestTemplateSearchDynamics`. Aggregate the events across all of those test methods into one answer. The primary target is `lark.tree_templates.TemplateConf._match_tree_template`, defined in `lark/tree_templates.py`.

Report invocation counts for the following location-defined scope: every module-level function defined directly in `lark/tree_templates.py`, plus every method defined directly in the body of every class defined directly in that file. Include `__init__`, other dunder methods, static methods, and class methods when directly defined there. Exclude inherited methods, property getter/setter/deleter functions, nested functions, closures, lambdas, comprehension frames, class-body execution frames, and methods of nested classes. A definition in this scope must be reported even if it never executes.

Function identity is the dotted runtime module name followed by the definition's qualified name, with no `<locals>` rewriting; for example, a hypothetical method would be `sample_pkg.mod.Widget.run`. The `file` value is always the repo-relative POSIX path of the defining source file, here `lark/tree_templates.py`.

One invocation means one Python tracing `call` event for that function's frame during the selected test run. Count events regardless of which frame caused them, including transitive and recursive calls. Do not count line, return, or exception events. A generator or coroutine emits another `call` event each time its suspended frame is resumed, and every such event counts as another invocation, including a final resume that runs the frame to completion. Do not deduplicate repeated call events.

Return a JSON object with exactly one key, `invocation_counts`. Its value is a list containing exactly one object per in-scope definition. Each object has exactly the keys `count` (JSON integer), `file` (JSON string), and `func` (JSON string). Functions that receive no qualifying call event have `count: 0`; no value is represented by JSON null or by an omitted entry. Sort the list by `func` ascending using ordinary Unicode code-point string order, with `file` ascending as the tie-breaker. There is no further normalization or formatting of names and no deduplication of definition records."""


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
    target_events = 0
    parsed_events = 0
    for line in lines:
        match = EVENT_RE.search(line)
        if not match:
            continue
        parsed_events += 1
        func = match.group("func")
        event = match.group("event")
        normalized_path = match.group("path").replace("\\", "/")
        if func == TARGET:
            target_events += 1
        if (
            event == "call"
            and func in scope_set
            and normalized_path.endswith("/" + REPO_FILE)
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

    source_path = Path.cwd() / REPO_FILE
    scope = scope_functions(source_path)
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
