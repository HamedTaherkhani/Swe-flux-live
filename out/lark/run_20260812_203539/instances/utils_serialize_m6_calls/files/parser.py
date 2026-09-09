#!/usr/bin/env python3
import argparse
import ast
from collections import Counter
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/utils.py"
TARGET_FUNC = "lark.utils.Serialize.serialize"
TEST_FILE = "lark_qa/utils_serialize_m6_calls/files/testcase.py"
TEST_CLASS = "TestSerializeCallGraphAggregation"
MODULE = "lark.utils"


def fail(message):
    raise RuntimeError(message)


def scoped_functions(source_path):
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names = set()
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, function_nodes):
            names.add("%s.%s" % (MODULE, node.name))
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, function_nodes):
                    names.add("%s.%s.%s" % (MODULE, node.name, member.name))

    if TARGET_FUNC not in names:
        fail("target function is absent from computed source scope: %s" % TARGET_FUNC)
    if not names:
        fail("computed source scope contains no functions")
    return names


def parse_trace(trace_path, source_path):
    if not trace_path.is_file():
        fail("trace log is missing: %s" % trace_path)
    if trace_path.stat().st_size == 0:
        fail("trace log is empty: %s" % trace_path)

    scope = scoped_functions(source_path)
    event_re = re.compile(
        r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
        r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    )
    counts = Counter()
    target_events = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_re.search(raw_line)
        if not match:
            continue
        filename = match.group("file").replace("\\", "/")
        if not filename.endswith("/" + TARGET_FILE):
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_events.append(event)
        if event == "call" and func in scope:
            counts[func] += 1

    if not target_events:
        fail("trace contains zero events for %s" % TARGET_FUNC)
    if "call" not in target_events:
        fail("trace contains no call event for %s" % TARGET_FUNC)

    return {
        "invocation_counts": [
            {"count": counts[func], "file": TARGET_FILE, "func": func}
            for func in sorted(scope)
        ]
    }


def build_question():
    return (
        "Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, run the pytest id "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate across ALL such test "
        "methods in that class. An individual method is identified by its full "
        "pytest id, for example "
        f"`{TEST_FILE}::{TEST_CLASS}::test_coprime_three_path`; method execution "
        "order does not affect the requested totals. The primary target is "
        f"`{TARGET_FUNC}` in `{TARGET_FILE}`. For the answer scope, inspect "
        f"`{TARGET_FILE}` as it exists in the repository and consider every "
        "module-level synchronous or asynchronous function definition and every "
        "synchronous or asynchronous method definition that appears directly in "
        "the body of a module-level class. Include `__init__` and every other "
        "dunder method, class methods, static methods, and functions decorated as "
        "property getters, setters, or deleters when their `def`/`async def` "
        "appears directly in that class body. Exclude lambdas, comprehension "
        "frames, generator-expression frames, nested functions or closures, "
        "functions inside nested classes, dynamically attached functions, and "
        "inherited methods whose definition is not in this file. "
        "Function identity is the dotted defining-module qualname "
        "`module.Class.method` for a method or `module.function` for a "
        "module-level function; for example, a method `run` defined by class "
        "`Widget` in module `sample.tools` is `sample.tools.Widget.run`. Use the "
        "defining module even when a method executes on a subclass instance. "
        "One invocation means one Python `call` event for that exact function's "
        "frame during the complete class run, including calls reached "
        "transitively, recursively, or from any caller frame. Count calls from "
        "all test methods and all setup/teardown activity occurring within the "
        "class run if they reach an in-scope frame. A generator or coroutine "
        "resumption that Python reports as another `call` event counts as "
        "another invocation. Calls to excluded frames do not count, even when "
        "their qualname begins with an in-scope qualname. Functions in scope "
        "that never receive a `call` event must still appear with `count: 0`. "
        "Aggregate all events having the same dotted qualname into exactly one "
        "entry; if repeated source definitions would produce the same dotted "
        "qualname, treat that qualname as one identity rather than emitting "
        "duplicates. Return exactly one JSON object with the sole key "
        "`invocation_counts`. Its value must be a JSON list containing one "
        "object per scoped function, each with exactly `count` (a JSON integer), "
        "`file` (the repo-relative JSON string `lark/utils.py`), and `func` (the "
        "dotted-qualname JSON string defined above). Sort entries by `func` "
        "ascending in Unicode code-point order; if two entries could share the "
        "same `func`, sort by `file` ascending as the tie-break, though the "
        "same-qualname aggregation rule leaves no duplicate entries. Do not "
        "deduplicate call events, and use no additional keys."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    answer = parse_trace(Path(args.trace_log), root_dir / TARGET_FILE)
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "invocation_counts": [
                {"count": "int", "file": "str", "func": "str"}
            ]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise
