#!/usr/bin/env python3
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import CodeType


QUESTION = """Run every pytest-collected test method whose name starts with `test_` in class `TestShortOptionParsingMatrix` from `click_qa/parser_match_short_opt_m6_calls/files/testcase.py`; equivalently, the covered pytest ids have the form `click_qa/parser_match_short_opt_m6_calls/files/testcase.py::TestShortOptionParsingMatrix::test_*`. Aggregate the events from all of those methods into one answer, regardless of the order in which pytest runs them.

The primary target is `click.parser._OptionParser._match_short_opt`, defined at lines 390-428 of `src/click/parser.py`. The tracked scope is every Python function code object lexically contained by the class body of `_OptionParser` in that file. Include `__init__`, all other dunder methods, directly defined instance, class, and static methods, property accessor functions, and every nested function, closure, lambda, generator expression, and comprehension frame inside those methods, recursively. Exclude the executable class-body code object itself, module-level functions, functions in other classes, and inherited methods. Determine this lexical scope from the repository version of the file, rather than from runtime attribute lookup.

For each in-scope function, report its total invocation count across the complete covered test run. One invocation means one Python tracing `call` event for that function's frame, whether reached directly, transitively, recursively, or from any caller. Calls from every frame count; calls outside the scope are not reported. A generator or coroutine resumption that produces another Python `call` event counts as another invocation. Do not infer counts from `return`, `line`, or `exception` events.

Function identity is the runtime module name followed by the code object's dotted qualified name, with components joined by periods. For example, `click.core.Command.parse_args` illustrates the required format. Use the repo-relative string `src/click/parser.py` as `file` for every entry. Emit exactly one entry for every function in scope; functions that have no qualifying call events must still appear with `count: 0`. Counts are JSON integers and `file` and `func` are JSON strings; no value uses `repr`, abbreviation, aliases, or an omitted/null substitute.

Return an object with the exact shape `{"invocation_counts": [{"count": int, "file": str, "func": str}, ...]}` and no additional keys. Sort entries by `func` ascending using ordinary Unicode code-point string ordering, with `file` ascending as the tie-breaker. Do not remove or merge entries except that all call events for the same in-scope function identity are summed into its single required entry."""


TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)
TARGET_FUNC = "click.parser._OptionParser._match_short_opt"
SOURCE_REL = Path("src/click/parser.py")
CLASS_NAME = "_OptionParser"


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def scoped_qualnames(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    try:
        module_code = compile(source, str(source_path), "exec")
    except SyntaxError as exc:
        fail(f"cannot compile target source {source_path}: {exc}")

    class_codes = [
        value
        for value in module_code.co_consts
        if isinstance(value, CodeType) and value.co_name == CLASS_NAME
    ]
    if len(class_codes) != 1:
        fail(f"expected exactly one top-level class code object named {CLASS_NAME}")

    qualnames = []

    def collect(container):
        for value in container.co_consts:
            if isinstance(value, CodeType):
                qualnames.append(value.co_qualname)
                collect(value)

    collect(class_codes[0])
    if not qualnames:
        fail(f"class {CLASS_NAME} contains no function code objects")
    if len(qualnames) != len(set(qualnames)):
        fail(f"class {CLASS_NAME} contains duplicate code-object qualnames")
    return qualnames


def parse_trace(trace_path, scoped_funcs):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    try:
        text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read trace log {trace_path}: {exc}")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    counts = Counter()
    event_count = 0
    target_event_count = 0
    for line in text.splitlines():
        match = TRACE_RE.search(line)
        if match is None:
            continue
        event_count += 1
        func = match.group("func")
        if func == TARGET_FUNC:
            target_event_count += 1
        if match.group("event") == "call" and func in scoped_funcs:
            counts[func] += 1

    if event_count == 0:
        fail("trace log contains no parseable events")
    if target_event_count == 0:
        fail(f"trace log contains zero events for target {TARGET_FUNC}")
    return counts


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    root = Path.cwd()
    source_path = root / SOURCE_REL
    qualnames = scoped_qualnames(source_path)
    scoped_funcs = {
        f"click.parser.{qualname}" for qualname in qualnames
    }
    counts = parse_trace(Path(args.trace_log), scoped_funcs)

    invocation_counts = [
        {
            "count": counts[func],
            "file": SOURCE_REL.as_posix(),
            "func": func,
        }
        for func in sorted(scoped_funcs)
    ]
    document = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [
                {"count": "int", "file": "str", "func": "str"}
            ]
        },
        "oracle_answer": {"invocation_counts": invocation_counts},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: unexpected parser failure: {exc}", file=sys.stderr)
        raise
