#!/usr/bin/env python3
import argparse
import ast
import builtins
import importlib
import json
import re
from pathlib import Path


TARGET_FILE = "src/instructlab/model/chat.py"
TARGET_FUNC = "instructlab.model.chat.chat_cli"
QUESTION = (
    "Run the pytest test "
    "`instruct_lab_qa/chat_chat_cli_s5_exceptions/files/testcase.py::"
    "ChatModelExceptionFlowTest::test_generated_prompt_failures_are_handled` "
    "against the repository as provided. During the complete run, consider every "
    "invocation of `instructlab.model.chat.chat_cli` in "
    "`src/instructlab/model/chat.py`. An invocation means one Python call of that "
    "function; invocations are numbered 1-based in chronological call order, and "
    "the answer is aggregated across all invocations. Report the set of concrete "
    "exception types caught inside that function. Here, an exception is caught "
    "inside the function only when it reaches an expression executing in a "
    "`chat_cli` frame and Python matches it to an `except` handler lexically "
    "belonging to that function; include exceptions originating in callees when "
    "they reach that frame, but exclude exceptions that propagate out without a "
    "matching handler. Multiple catches of the same normalized type contribute "
    "one set member. Exception type naming MUST use this convention: bare "
    "`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never "
    "`builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`haystack.core.errors.PipelineError`). Return exactly "
    "`{\"caught_exception_kinds\": [<strings>]}`. Sort the normalized strings in "
    "ascending lexicographic order by Unicode code point; this is also the sole "
    "tie-breaker after deduplication. The list is JSON, and each element is the "
    "type-name string itself, not `repr()` or `str()` of an exception object."
)


def handler_names(node):
    if node is None:
        return {"BaseException"}
    if isinstance(node, (ast.Name, ast.Attribute)):
        return {ast.unparse(node).rsplit(".", 1)[-1]}
    if isinstance(node, ast.Tuple):
        names = set()
        for element in node.elts:
            names.update(handler_names(element))
        return names
    return set()


def caught_at_line(tree, line, exception_name):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not node.body:
            continue
        body_start = min(item.lineno for item in node.body)
        body_end = max(item.end_lineno for item in node.body)
        if not body_start <= line <= body_end:
            continue
        for handler in node.handlers:
            if exception_name in handler_names(handler.type):
                return True
    return False


def normalized_type_name(short_name):
    value = getattr(builtins, short_name, None)
    if isinstance(value, type) and issubclass(value, BaseException):
        return value.__name__

    module = importlib.import_module("instructlab.model.chat")
    value = getattr(module, short_name, None)
    if isinstance(value, type) and issubclass(value, BaseException):
        return f"{value.__module__}.{value.__qualname__}"

    for imported in vars(module).values():
        value = getattr(imported, short_name, None)
        if isinstance(value, type) and issubclass(value, BaseException):
            return f"{value.__module__}.{value.__qualname__}"
    raise RuntimeError(f"cannot resolve traced exception type {short_name!r}")


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    target_events = [
        line
        for line in trace_text.splitlines()
        if f" {TARGET_FUNC} event=" in line and f"/{TARGET_FILE}:" in line
    ]
    if not target_events:
        raise SystemExit(
            f"ERROR: trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise SystemExit(f"ERROR: target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=TARGET_FILE)

    exception_pattern = re.compile(
        rf"/{re.escape(TARGET_FILE)}:(\d+) "
        rf"{re.escape(TARGET_FUNC)} event=exception exc=([^: ]+):"
    )
    caught = set()
    for line in target_events:
        match = exception_pattern.search(line)
        if not match:
            continue
        source_line = int(match.group(1))
        short_name = match.group(2)
        if caught_at_line(tree, source_line, short_name):
            caught.add(normalized_type_name(short_name))

    if not caught:
        raise SystemExit(
            f"ERROR: no caught exceptions found for {TARGET_FUNC} in traced run"
        )

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": sorted(caught)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
