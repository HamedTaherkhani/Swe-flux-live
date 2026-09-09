#!/usr/bin/env python3
import argparse
import builtins
import inspect
import json
import re
from pathlib import Path

import lark.exceptions


TARGET_PATH = "/lark/parsers/lalr_parser.py"
TARGET_FUNC = "lark.parsers.lalr_parser.LALR_Parser.parse"

QUESTION = (
    "Run only the pytest test "
    "`lark_qa/lalr_parser_parse_s5_exceptions/files/testcase.py::"
    "TestLalrParserRecovery::test_generated_recovery_stream`. Consider only "
    "the invocation made by the explicit `target.parse(lexer_thread, "
    "\"start\", on_error=recover)` statement in that test, excluding any "
    "invocations performed internally while `Lark` is being constructed. "
    "For that invocation of `lark.parsers.lalr_parser.LALR_Parser.parse` in "
    "`lark/parsers/lalr_parser.py`, which distinct exception types are caught "
    "by an `except` handler inside the invocation, allowing it to continue "
    "and return normally? An exception counts as caught when it is raised "
    "into the active target frame by a call made at line 42 or line 61 and "
    "control then enters one of the target's matching `except` suites; exclude "
    "exceptions handled wholly outside the target and any exception that "
    "propagates out to its caller. Invocation means one runtime `call` of this "
    "exact method, numbered 1-based in chronological order. Deduplicate types "
    "across all catches, then sort the resulting strings in ascending "
    "lexicographic Unicode-code-point order. Name each type using bare "
    "`type(exc).__name__` for built-in exceptions (for example, `ValueError`, "
    "never `builtins.ValueError`) and using `type(exc).__module__ + \".\" + "
    "type(exc).__qualname__` for every non-built-in exception (for example, "
    "`haystack.core.errors.PipelineError`). Return exactly a JSON object with "
    "the single key "
    "`caught_exception_kinds`, whose value is the sorted list of strings; "
    "duplicates are removed before sorting."
)


def type_catalog():
    catalog = {}
    for name, value in vars(builtins).items():
        if inspect.isclass(value) and issubclass(value, BaseException):
            catalog[name] = value
    for name, value in vars(lark.exceptions).items():
        if inspect.isclass(value) and issubclass(value, BaseException):
            catalog[name] = value
    return catalog


def canonical_type_name(exc_type):
    if exc_type.__module__ == "builtins":
        return exc_type.__name__
    return f"{exc_type.__module__}.{exc_type.__qualname__}"


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_lines = [
        line
        for line in text.splitlines()
        if TARGET_PATH in line and f" {TARGET_FUNC} event=" in line
    ]
    if not target_lines:
        raise RuntimeError("trace contains zero events for the target function")

    invocations = []
    current = None
    for line in target_lines:
        if " event=call " in line:
            if current is not None:
                raise RuntimeError("encountered nested or incomplete target invocation")
            current = [line]
        elif current is not None:
            current.append(line)
            if " event=return " in line:
                invocations.append(current)
                current = None
    if current is not None:
        raise RuntimeError("target trace ended during an invocation")

    selected = [
        invocation
        for invocation in invocations
        if "'on_error': '<function " in invocation[0]
    ]
    if len(selected) != 1:
        raise RuntimeError(
            f"expected one direct invocation with a recovery callback, found {len(selected)}"
        )
    selected_lines = selected[0]
    if "retval=None " in selected_lines[-1]:
        raise RuntimeError("selected target invocation did not return a result")

    event_pattern = re.compile(r" event=exception exc=([A-Za-z_][A-Za-z0-9_]*): ")
    raw_names = []
    for line in selected_lines:
        match = event_pattern.search(line)
        if match:
            raw_names.append(match.group(1))
    if not raw_names:
        raise RuntimeError("target trace contains no exception events")

    catalog = type_catalog()
    unknown = sorted(set(raw_names) - set(catalog))
    if unknown:
        raise RuntimeError(f"cannot resolve exception type names: {unknown}")

    caught = sorted({canonical_type_name(catalog[name]) for name in raw_names})
    if len(caught) < 2:
        raise RuntimeError(f"expected at least two caught exception kinds, found {caught}")
    return {"caught_exception_kinds": caught}


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": parse_trace(Path(args.trace_log)),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
