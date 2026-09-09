#!/usr/bin/env python3
import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


REPO_RELATIVE_FILE = "sqlglot/optimizer/scope.py"
MODULE = "sqlglot.optimizer.scope"
TARGET = f"{MODULE}._traverse_scope"
CALL_RE = re.compile(
    r"^(?:\S+ \S+ )?(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """Run every pytest test method in class `TestScopeTraversalCalls` from `sqlglot_qa/scope_traverse_scope_m6_calls/files/testcase.py`, equivalently the pytest class id `sqlglot_qa/scope_traverse_scope_m6_calls/files/testcase.py::TestScopeTraversalCalls`. Aggregate across all methods of that class whose names start with `test_`; do not report per-method results. The aggregation is a sum and no event sequence is reported, so pytest's method execution order does not affect the requested answer.

The primary target is `sqlglot.optimizer.scope._traverse_scope`, defined in `sqlglot/optimizer/scope.py`. Consider every module-level function defined directly in `sqlglot/optimizer/scope.py` and every method defined directly in that file's class `Scope`. Concretely, include each `ast.FunctionDef` or `ast.AsyncFunctionDef` that is a direct child of either the module AST or the `Scope` class body, including decorated methods, properties, `__init__`, and dunder methods. Exclude methods of any other class, inherited methods, nested functions, closures, lambda bodies, and comprehension code objects.

For each in-scope function, report its invocation count over the complete class run. One invocation means one Python tracing `call` event for that function's frame, whether reached directly, transitively, recursively, or from any other frame. Count every such event without deduplication. CPython generator or coroutine resumption emits another `call` event for the suspended frame, so each resumption counts as another invocation. Calls to functions outside the located scope are not reported.

Function identity is the dotted Python module name followed by the function's dotted `__qualname__`, with no filename, line number, or `()` suffix; for example, a hypothetical method `Scope.example_method` in this module would be `sqlglot.optimizer.scope.Scope.example_method`. The `file` value is always the repository-relative POSIX path `sqlglot/optimizer/scope.py`. Functions and methods in scope that receive no qualifying call events must still appear with `count: 0`.

Return exactly `{"invocation_counts": [{"count": <integer>, "file": <string>, "func": <string>}, ...]}`. Emit one object per in-scope function, retain no duplicate function entries, and sort objects by `func` ascending; if two entries could share a `func`, break the tie by `file` ascending. Counts are base-10 JSON integers, and `file` and `func` are JSON strings."""


def module_functions(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = [node.name for node in tree.body if isinstance(node, function_nodes)]
    scope_class = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Scope"),
        None,
    )
    if scope_class is None:
        raise RuntimeError(f"class Scope not found in {source_path}")
    names.extend(
        f"Scope.{node.name}" for node in scope_class.body if isinstance(node, function_nodes)
    )
    if not names:
        raise RuntimeError(f"no module-level functions found in {source_path}")
    return sorted(names)


def parse_trace(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    names = module_functions(source_path)
    funcs = {f"{MODULE}.{name}" for name in names}
    counts = Counter()
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = CALL_RE.match(raw_line)
        if not match:
            continue
        func = match.group("func")
        if func == TARGET:
            target_events += 1
        if match.group("event") == "call" and func in funcs:
            counts[func] += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for target function {TARGET}")

    return {
        "invocation_counts": [
            {
                "count": counts[func],
                "file": REPO_RELATIVE_FILE,
                "func": func,
            }
            for func in sorted(funcs)
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    answer = parse_trace(Path(args.trace_log), repo_root / REPO_RELATIVE_FILE)
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
