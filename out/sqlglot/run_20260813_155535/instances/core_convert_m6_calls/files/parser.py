#!/usr/bin/env python3
import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


REPO_RELATIVE_FILE = "sqlglot/expressions/core.py"
MODULE = "sqlglot.expressions.core"
TARGET = f"{MODULE}.convert"
CALL_RE = re.compile(
    r"^(?:\S+ \S+ )?(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """Run every pytest test method in class `TestConvertCallGraph` from `sqlglot_qa/core_convert_m6_calls/files/testcase.py`, equivalently the pytest class id `sqlglot_qa/core_convert_m6_calls/files/testcase.py::TestConvertCallGraph`. Aggregate by summing across all methods defined by that class whose names start with `test_`; each individual method has a pytest id formed by appending `::<method_name>` to that class id. Do not report per-method results. Because only summed counts are requested, method execution order does not affect the answer.

The primary target is `sqlglot.expressions.core.convert`, defined in `sqlglot/expressions/core.py`. The tracked scope is every module-level function defined directly in that file. More precisely, include the unique names of all `ast.FunctionDef` and `ast.AsyncFunctionDef` nodes that are direct children of the module AST, including decorated functions. If several direct definitions have the same name, such as overload declarations followed by an implementation, they denote one dotted function identity and produce one answer entry. Exclude every class method and property accessor (including `__init__`, dunder methods, and methods inherited by any class), as well as nested functions, closures, lambda bodies, and comprehension code objects.

For each in-scope function, report its invocation count over the complete class run. One invocation is one Python `call` event for that function's frame, including calls reached directly, transitively, recursively, or from any other frame. Count every qualifying event without event-level deduplication. A CPython generator or coroutine resumption emits another `call` event for its suspended frame, so each such resumption counts again. Calls for frames outside the located scope are not reported. Every in-scope function must have exactly one answer entry even if it never executes, in which case its count is the JSON integer `0`.

Function identity is the dotted module name followed by the function's dotted `__qualname__`, with no filename, line number, or `()` suffix. For example, a hypothetical direct function named `sample_helper` in this module would be `sqlglot.expressions.core.sample_helper`. The `file` value is the repository-relative POSIX path `sqlglot/expressions/core.py`; both `file` and `func` are serialized directly as JSON strings, not as Python `repr` strings.

Return exactly `{"invocation_counts": [{"count": <integer>, "file": <string>, "func": <string>}, ...]}`. Counts are base-10 JSON integers. Retain no duplicate function entries and sort entries by `func` ascending; if two entries could share a `func`, break the tie by `file` ascending."""


def module_function_names(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = sorted({node.name for node in tree.body if isinstance(node, function_nodes)})
    if not names:
        raise RuntimeError(f"no direct module-level functions found in {source_path}")
    return names


def parse_trace(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    funcs = {f"{MODULE}.{name}" for name in module_function_names(source_path)}
    counts = Counter()
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = CALL_RE.match(raw_line)
        if not match:
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET:
            target_events += 1
        if event == "call" and func in funcs:
            counts[func] += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for target function {TARGET}")

    return {
        "invocation_counts": [
            {"count": counts[func], "file": REPO_RELATIVE_FILE, "func": func}
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
