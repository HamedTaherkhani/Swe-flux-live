#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


MODULE = "haystack.components.converters.msg"
RELATIVE_FILE = "haystack/components/converters/msg.py"
CLASS_NAME = "MSGToDocument"
TARGET_TRACE_FUNC = f"{MODULE}._convert"
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run every pytest test method directly defined on
`TestMSGConvertInvocationCounts` in
`haystack_qa/msg_convert_m6_calls/files/testcase.py`; equivalently, run the
pytest class id
`haystack_qa/msg_convert_m6_calls/files/testcase.py::TestMSGConvertInvocationCounts`,
which covers every directly defined method whose name starts with `test_`.
Aggregate one answer across all of those test methods, rather than producing
per-test answers. The execution reaches the primary target
`haystack.components.converters.msg.MSGToDocument._convert` in
`haystack/components/converters/msg.py` through the component's public caller.

For the tracked scope, consider every method directly defined in the source
body of class `MSGToDocument` in `haystack/components/converters/msg.py`.
Include instance methods, static methods, class methods, `__init__`, and any
other dunder method directly defined there. Exclude module-level functions,
inherited methods, property getter/setter/deleter functions, and functions
created inside a method, including nested functions, closures, generator
expressions, and comprehension frames.

Function identity is the dotted Python module name followed by the code
object's dotted qualified name, with no filename or line suffix; for example,
a method could be written as `some.pkg.Widget.process`. The `file` value is
the repository-relative POSIX path of the file containing the direct method
definition, so it uses `/` separators.

Count one invocation for each Python `call` trace event for the frame of an
in-scope method during the complete class run, regardless of which frame
called it. Thus direct, transitive, and recursive calls from any frame all
count. Calls to out-of-scope functions do not create answer entries.
If an in-scope generator or coroutine frame is resumed and Python emits
another `call` event for that resumption, count that event as another
invocation. Sum all such events across all test methods. Do not deduplicate
events. Emit exactly one entry for every in-scope method; if it emits no
`call` event, emit it with `count: 0`.

Return a JSON object with the sole key `invocation_counts`. Its value is a
list of objects having exactly `count` (a base-10 JSON integer), `file` (a
JSON string), and `func` (a JSON string). Sort entries by `func` ascending,
breaking a hypothetical equal-`func` tie by `file` ascending. No reported
value uses Python `repr`, and no field is omitted or represented by JSON
null."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def scoped_functions(source_path: Path) -> list[str]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot inspect target source {source_path}: {exc}")

    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME), None
    )
    if class_node is None:
        fail(f"class {CLASS_NAME!r} not found in {source_path}")

    names = []
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator_names = {
            decorator.id
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Name)
        }
        decorator_attrs = {
            decorator.attr
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Attribute)
        }
        if "property" in decorator_names or decorator_attrs.intersection({"setter", "deleter"}):
            continue
        names.append(f"{MODULE}.{CLASS_NAME}.{node.name}")

    if not names:
        fail(f"no directly defined methods found on {CLASS_NAME}")
    return sorted(names)


def parse_events(trace_path: Path) -> list[tuple[str, str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match:
            events.append((match.group("func"), match.group("event")))
    if not events:
        fail("trace log contains no parseable runtime events")
    if not any(func == TARGET_TRACE_FUNC for func, _event in events):
        fail(f"trace log contains zero events for target function {MODULE}.{CLASS_NAME}._convert")
    return events


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / RELATIVE_FILE
    functions = scoped_functions(source_path)
    events = parse_events(args.trace_log)
    trace_name_to_function = {
        f"{MODULE}.{func.rpartition('.')[2]}": func
        for func in functions
    }
    counts = Counter(
        trace_name_to_function[func]
        for func, event in events
        if event == "call" and func in trace_name_to_function
    )

    invocation_counts = [
        {"count": counts[func], "file": RELATIVE_FILE, "func": func}
        for func in functions
    ]
    invocation_counts.sort(key=lambda entry: (entry["func"], entry["file"]))

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": {"invocation_counts": invocation_counts},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
