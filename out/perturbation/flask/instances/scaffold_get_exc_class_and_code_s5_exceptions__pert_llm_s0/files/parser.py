import argparse
import ast
import builtins
import json
from pathlib import Path
import re
import sys


INSTANCE_TEST = (
    "flask_qa/scaffold_get_exc_class_and_code_s5_exceptions/files/testcase.py::"
    "TestErrorHandlerRegistration::test_seeded_registration_matrix_then_instance"
)
TARGET_FILE = "src/flask/sansio/scaffold.py"
TARGET_FUNC = "flask.sansio.scaffold.Scaffold._get_exc_class_and_code"

QUESTION = f"""Run the pytest test `{INSTANCE_TEST}` against this repository. Consider
the final invocation of `{TARGET_FUNC}` in `{TARGET_FILE}`, namely the
invocation reached from the last `Flask.register_error_handler` call inside
the test's `assertRaises` context. What exact exception propagates out of that
target invocation to its caller?

An invocation is one entry into exactly `{TARGET_FUNC}`, counted 1-based in
chronological order over the whole test run; "final" means the invocation with
the greatest such index. Report only the exception that leaves that target
frame. Exclude exceptions from all earlier invocations, exceptions raised in
nested callees, and any exception caught and handled within the selected
target invocation. There is exactly one propagated exception to report, so no
sorting, tie-breaking, or deduplication applies.

Return exactly one JSON object with the shape
`{{"exception_message": "str", "exception_type": "str"}}`, with no other keys.
`exception_message` is exact `str(exc)`, character for character; it is the
decoded JSON string value, with JSON escaping used only as required to encode
that string (an absent message would be the empty string `""`, never `null` or
an omitted key). Exception type naming MUST use this convention: bare
`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never
`builtins.ValueError`), and `module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`)."""


def exception_from_trace(raw: str) -> tuple[str, str]:
    prefix, separator, exception_repr = raw.partition(": ")
    if not separator or not prefix:
        raise RuntimeError(f"malformed exception payload: {raw!r}")

    try:
        expression = ast.parse(exception_repr, mode="eval").body
    except SyntaxError as exc:
        raise RuntimeError(
            f"exception repr is not a parseable expression: {exception_repr!r}"
        ) from exc

    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != prefix
        or expression.keywords
    ):
        raise RuntimeError(f"unsupported exception repr: {exception_repr!r}")

    try:
        args = [ast.literal_eval(argument) for argument in expression.args]
    except (TypeError, ValueError, SyntaxError) as exc:
        raise RuntimeError(
            f"exception arguments are not literals: {exception_repr!r}"
        ) from exc

    exception_class = getattr(builtins, prefix, None)
    if (
        not isinstance(exception_class, type)
        or not issubclass(exception_class, BaseException)
    ):
        raise RuntimeError(
            "trace does not provide the module and qualname needed to normalize "
            f"non-built-in exception type {prefix!r}"
        )

    reconstructed = exception_class(*args)
    return type(reconstructed).__name__, str(reconstructed)


def parse_trace(trace_path: Path) -> dict:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"(?P<file>\S*src/flask/sansio/scaffold\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
        r"(?P<rest>.*)$"
    )
    exception_pattern = re.compile(r"^ exc=(?P<exception>.*?) locals=")
    invocations = []
    current = None
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                raise RuntimeError("overlapping target invocations in trace")
            current = []
            invocations.append(current)
        elif current is None:
            raise RuntimeError(f"target {event} event occurred outside an invocation")
        elif event == "exception":
            exception_match = exception_pattern.match(match.group("rest"))
            if exception_match is None:
                raise RuntimeError(
                    f"target exception event has malformed payload: {raw_line!r}"
                )
            current.append(("exception", exception_match.group("exception")))
        elif event == "line":
            current.append(("line", None))
        elif event == "return":
            current.append(("return", None))
            current = None

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )
    if current is not None:
        raise RuntimeError("trace ended during a target invocation")
    if not invocations:
        raise RuntimeError("trace contains no complete target invocation")

    selected = invocations[-1]
    exceptions = [
        payload for event, payload in selected if event == "exception"
    ]
    if not exceptions:
        raise RuntimeError("final target invocation contains no exception event")

    events_before_return = [
        event for event, _payload in selected if event != "return"
    ]
    if not events_before_return or events_before_return[-1] != "exception":
        raise RuntimeError(
            "final target exception was followed by target execution and was handled"
        )

    exception_type, exception_message = exception_from_trace(exceptions[-1])
    return {
        "exception_message": exception_message,
        "exception_type": exception_type,
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    answer = parse_trace(args.trace_log)
    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote oracle to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
