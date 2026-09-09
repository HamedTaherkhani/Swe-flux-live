from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


MODULE = "click._winconsole"
SOURCE_FILE = "src/click/_winconsole.py"
TARGET = "click._winconsole._WindowsConsoleWriter.write"

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest node
`click_qa/winconsole_write_m6_calls/files/testcase.py::WindowsConsoleWriterCallGraphTest`,
which runs and aggregates all methods of that class whose names begin with
`test_`; equivalently, include every pytest method id formed by appending
`::<method-name>` to that class node. During that complete class run, the
primary target is `click._winconsole._WindowsConsoleWriter.write` in
`src/click/_winconsole.py`.

For every Python function and method defined in `src/click/_winconsole.py`,
report its total invocation count across all of those test methods. The scope
includes every module-level `def` or `async def`, including definitions in a
module-level conditional or exception-handling suite, and every `def` or
`async def` belonging to a class defined directly at module level. For a
module-level class, include its directly defined methods even when decorated:
property getter methods, static methods, class methods, `__init__`, and all
other dunder methods are included. Exclude imported functions, lambdas,
comprehension frames, nested functions and closures, methods of nested
classes, and inherited methods that are not defined in this file.

Function identity is the full dotted runtime qualname
`module.Class.method` or `module.function`; for example,
`click.core.Command.main`. One invocation means one Python `call` event that
begins or resumes that function's frame, regardless of which frame caused it:
include direct, transitive, and recursive calls from anywhere during any
included test method. A generator or coroutine resumption that produces
another Python `call` event therefore counts as another invocation. Calls to
functions outside the located scope do not count. Sum counts across all test
methods rather than reporting per-method counts. Every in-scope function must
appear exactly once; if it has no such event, report `count: 0`.

Return JSON with exactly one key, `invocation_counts`, whose value is a list
of objects. Each object has exactly `count` (a JSON integer), `file` (a JSON
string), and `func` (a JSON string). `file` is the POSIX repo-relative path of
the definition file, so all entries use the located source file's path;
`func` uses the dotted identity rule above. Sort entries by `func` ascending,
with `file` ascending as the tie-breaker if identities are equal. Do not
deduplicate runtime calls before counting. Use ordinary JSON serialization;
there are no `repr`-formatted values, exception names, or line numbers in the
answer."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def functions_in_scope(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: list[str] = []

    def walk_suites(statements: list[ast.stmt], class_name: str | None) -> None:
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{class_name}.{node.name}" if class_name else node.name
                names.append(f"{MODULE}.{qualname}")
                continue

            if isinstance(node, ast.ClassDef):
                if class_name is None:
                    walk_suites(node.body, node.name)
                continue

            for _field, value in ast.iter_fields(node):
                if isinstance(value, list) and all(
                    isinstance(item, ast.stmt) for item in value
                ):
                    walk_suites(value, class_name)
                elif isinstance(value, ast.ExceptHandler):
                    walk_suites(value.body, class_name)

    walk_suites(tree.body, None)

    if not names:
        fail(f"no functions found in scope from {source_path}")
    if len(names) != len(set(names)):
        fail("duplicate dotted function identities found in source scope")
    return sorted(names)


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)

    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")

    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    source_path = Path.cwd() / SOURCE_FILE
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    scoped_functions = functions_in_scope(source_path)
    scoped_set = set(scoped_functions)
    counts: Counter[str] = Counter()
    target_events = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue

        func = match.group("func")
        event = match.group("event")

        if func == TARGET:
            target_events += 1

        if event == "call" and func in scoped_set:
            counts[func] += 1

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET}")
    if counts[TARGET] == 0:
        fail(f"trace contains zero call events for target function {TARGET}")

    invocation_counts = [
        {"count": counts[func], "file": SOURCE_FILE, "func": func}
        for func in scoped_functions
    ]
    invocation_counts.sort(key=lambda item: (item["func"], item["file"]))

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": {"invocation_counts": invocation_counts},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
