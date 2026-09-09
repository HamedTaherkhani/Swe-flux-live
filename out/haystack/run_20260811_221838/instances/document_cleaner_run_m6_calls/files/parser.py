#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


QUESTION_KIND = "M6_InterProceduralCFG"
REPO_FILE = "haystack/components/preprocessors/document_cleaner.py"
MODULE = "haystack.components.preprocessors.document_cleaner"
CLASS_NAME = "DocumentCleaner"
TARGET = f"{MODULE}.{CLASS_NAME}.run"
TRACE_TARGET = f"{MODULE}.run"
TEST_SELECTION = (
    "haystack_qa/document_cleaner_run_m6_calls/files/"
    "testcase.py::TestDocumentCleanerInvocationCounts"
)
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+?):(?P<line>[1-9]\d*) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = f"""Run the pytest selection `{TEST_SELECTION}` from the repository root. This selects every test method directly defined on `TestDocumentCleanerInvocationCounts` whose name starts with `test_`; pytest identifies each one as `{TEST_SELECTION}::METHOD_NAME`. Produce one aggregate answer summed across all selected test methods, not one answer per method. Test execution order does not affect these summed counts.

The primary target is `{TARGET}` in `{REPO_FILE}`. The tracked scope is every method whose `def` or `async def` statement occurs directly in the source body of class `{CLASS_NAME}` in exactly that file. Include directly defined instance methods, static methods, class methods, `__init__`, and other directly defined dunder methods. Exclude module-level functions, imported functions, inherited methods, property getter/setter/deleter functions, and every function created inside a method, including nested functions, closures, lambda bodies, generator-expression frames, and comprehension frames.

For each method in the tracked scope, count one invocation for each Python `call` event for that method's frame during the complete selected pytest run, regardless of the caller. Calls made directly by tests, transitively by another function, recursively, or from any other frame all count. Do not deduplicate events. Calls to excluded or otherwise out-of-scope functions create no answer entry. If an in-scope generator or coroutine frame is resumed and Python emits another `call` event for that resumption, count that event as another invocation. Include every in-scope method exactly once even if it never executes; such a method has `count: 0`.

Function identity is the dotted source identity formed from the Python module name, the directly containing class name, and the method name, with no file or line suffix. For example, a hypothetical method may be represented as `sample.pkg.Widget.process`. Use this source identity even if runtime decoration changes a code object's `__qualname__`. The `file` value is the repository-relative POSIX path of the direct definition, using `/` separators; here it is `{REPO_FILE}` for every entry.

Return exactly one JSON object with the sole key `invocation_counts`. Its value is a JSON list containing one object per in-scope method, and each object has exactly the keys `count`, `file`, and `func`. `count` is a base-10 JSON integer; `file` and `func` are JSON strings containing the values defined above, not Python `repr` strings. No field is omitted and no value is represented by JSON `null`. Sort the entries by `func` ascending in ordinary Unicode code-point order, using `file` ascending as the tie-breaker if two entries hypothetically share the same `func`; perform no other reordering or deduplication."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def scoped_methods(source_path: Path) -> list[str]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot inspect target source {source_path}: {exc}")

    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME
        ),
        None,
    )
    if class_node is None:
        fail(f"class {CLASS_NAME!r} not found in {source_path}")

    methods = []
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        simple_decorators = {
            decorator.id
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Name)
        }
        attribute_decorators = {
            decorator.attr
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Attribute)
        }
        if "property" in simple_decorators or attribute_decorators.intersection(
            {"setter", "deleter"}
        ):
            continue
        methods.append(f"{MODULE}.{CLASS_NAME}.{node.name}")

    if not methods:
        fail(f"no directly defined methods found on class {CLASS_NAME}")
    return sorted(methods)


def parse_trace(trace_path: Path, methods: list[str]) -> dict:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    trace_name_to_method = {
        f"{MODULE}.{method.rpartition('.')[2]}": method for method in methods
    }
    counts = Counter()
    matching_file_events = 0
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(f"/{REPO_FILE}"):
            continue
        matching_file_events += 1
        func = match.group("func")
        if func == TRACE_TARGET:
            target_events += 1
        if match.group("event") == "call" and func in trace_name_to_method:
            counts[trace_name_to_method[func]] += 1

    if matching_file_events == 0:
        fail(f"trace log contains no events from {REPO_FILE}")
    if target_events == 0:
        fail(f"trace log contains zero events for target function {TARGET}")

    entries = [
        {"count": counts[func], "file": REPO_FILE, "func": func}
        for func in methods
    ]
    entries.sort(key=lambda entry: (entry["func"], entry["file"]))
    return {"invocation_counts": entries}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    methods = scoped_methods(Path.cwd() / REPO_FILE)
    oracle_answer = parse_trace(args.trace_log, methods)
    payload = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
