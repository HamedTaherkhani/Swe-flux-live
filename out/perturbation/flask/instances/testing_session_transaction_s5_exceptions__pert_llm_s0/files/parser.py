#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "/src/flask/testing.py"
TARGET_FUNC = "flask.testing.FlaskClient.session_transaction"
EXCEPTION_RE = re.compile(
    r"^(?P<prefix>.*?/src/flask/testing\.py):(?P<line>\d+) "
    r"flask\.testing\.FlaskClient\.session_transaction "
    r"event=exception exc=(?P<type>[A-Za-z_][A-Za-z0-9_]*): "
    r"(?P<value>.*?) locals="
)


def parse_exception_value(type_name, value_repr):
    try:
        expression = ast.parse(value_repr, mode="eval").body
    except SyntaxError as error:
        raise RuntimeError(f"cannot parse exception representation: {value_repr!r}") from error

    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        raise RuntimeError(f"unexpected exception representation: {value_repr!r}")
    if expression.func.id != type_name or len(expression.args) != 1 or expression.keywords:
        raise RuntimeError(f"unsupported exception representation: {value_repr!r}")

    try:
        argument = ast.literal_eval(expression.args[0])
    except (ValueError, SyntaxError) as error:
        raise RuntimeError(f"exception argument is not a literal: {value_repr!r}") from error

    exception_class = getattr(builtins, type_name, None)
    if not isinstance(exception_class, type) or not issubclass(exception_class, BaseException):
        raise RuntimeError(
            f"trace does not provide the module needed for non-built-in type {type_name!r}"
        )

    try:
        message = str(exception_class(argument))
    except Exception as error:
        raise RuntimeError(f"cannot reconstruct exception message: {value_repr!r}") from error
    return type_name, message


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
        if TARGET_FILE in line and f" {TARGET_FUNC} event=" in line
    ]
    if not target_events:
        raise SystemExit(
            f"ERROR: trace contains zero events for target function {TARGET_FUNC}"
        )

    exception_matches = [
        match
        for line in target_events
        if (match := EXCEPTION_RE.match(line)) is not None
    ]
    if len(exception_matches) != 1:
        raise SystemExit(
            "ERROR: expected exactly one target exception event, "
            f"found {len(exception_matches)}"
        )

    match = exception_matches[0]
    exception_type, exception_message = parse_exception_value(
        match.group("type"), match.group("value")
    )

    question = (
        "Run the pytest test "
        "`flask_qa/testing_session_transaction_s5_exceptions/files/testcase.py::"
        "TestSessionTransactionExceptions::test_final_generated_request_propagates` "
        "from the repository root. During that run, consider direct invocations of "
        "`FlaskClient.session_transaction` (runtime qualified name "
        "`flask.testing.FlaskClient.session_transaction`) in "
        "`src/flask/testing.py`. What are the type and message of the exception that "
        "propagates out of that target function's last chronological invocation and "
        "is received by the test's broad exception handler? An invocation means one "
        "entry into the target caused by entering one of the test's "
        "`with client.session_transaction(...)` statements; generator suspension "
        "and resumption within that same context manager remain part of the same "
        "invocation. Invocations are numbered 1-based in chronological order. "
        "Consider only an exception escaping the target frame; ignore exception "
        "events in every other function. Here, 'propagates out' means the exception "
        "is not handled by the target and is the object delivered to the caller's "
        "handler. Report `exception_message` as exact `str(exc)`, character for "
        "character, not `repr(exc)`. Exception type naming MUST use this convention: "
        "bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — "
        "never `builtins.ValueError`), and `module.QualName` for all others (e.g. "
        "`haystack.core.errors.PipelineError`). Return a JSON object with exactly "
        "the string keys `exception_message` and `exception_type`, each having a "
        "string value. There are no list values, so sorting, tie-breaking, and "
        "deduplication do not apply; no missing, empty, or null sentinel is used."
    )

    result = {
        "question_kind": "S5_Exceptions",
        "question": question,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": {
            "exception_message": exception_message,
            "exception_type": exception_type,
        },
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
