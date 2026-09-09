#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/docs.py"
TARGET_FUNC = "scripts.docs.stage_zensical_docs"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bevent=exception exc=(?P<exc>.*?) locals=")

QUESTION = """Run the pytest test
`fastapi_qa/docs_stage_zensical_docs_s5_exceptions/files/testcase.py::TestZensicalDocsFailure::test_programmatic_translation_failure`
against this repository. During that test, consider the first and only
invocation of `scripts.docs.stage_zensical_docs` whose code is in
`scripts/docs.py`. An invocation means one entry into exactly that function's
frame, counted 1-based in chronological order; frames for its callees and for
its nested comprehension code are not separate target invocations.

That invocation terminates by propagating an exception out of
`scripts.docs.stage_zensical_docs` to its caller. What are the exact type and
message of that propagated exception? Report exactly one JSON object with this
shape:
`{"exception_message": "str", "exception_type": "str"}`.
Both keys are required strings; neither an omitted key, an empty substitute,
nor JSON `null` represents a missing value.

Use this exception type naming convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`). The `exception_message` is exact
`str(exc)`, character for character; it is not `repr(exc)`, is not truncated,
and receives no quote or whitespace normalization.

Count only the exception that leaves the exact target frame in its first and
only invocation. Do not report exceptions that occur only in a callee or
nested-comprehension frame and are handled before the target frame exits. If
the same propagating exception produces events while multiple frames unwind,
the event in the outer `scripts.docs.stage_zensical_docs` frame contributes
the exception exactly once. There is one reported exception, so no sorting or
deduplication is applied and source line numbers are not part of the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def exception_from_trace(raw: str) -> BaseException:
    traced_type, separator, representation = raw.partition(": ")
    if not separator or not traced_type or not representation:
        fail(f"malformed exception trace payload: {raw!r}")

    exception_class = getattr(builtins, traced_type, None)
    if (
        not isinstance(exception_class, type)
        or not issubclass(exception_class, BaseException)
    ):
        fail(f"expected a built-in exception type, got {traced_type!r}")

    try:
        expression = ast.parse(representation, mode="eval").body
    except SyntaxError as error:
        fail(f"could not parse exception repr {representation!r}: {error}")
    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != traced_type
        or expression.keywords
    ):
        fail(f"unsupported exception repr: {representation!r}")
    try:
        args = tuple(ast.literal_eval(argument) for argument in expression.args)
    except (TypeError, ValueError, SyntaxError) as error:
        fail(f"exception repr has non-literal arguments: {error}")

    reconstructed = exception_class(*args)
    if type(reconstructed).__name__ != traced_type:
        fail(f"reconstructed exception type mismatch for {traced_type!r}")
    return reconstructed


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            traced_file = match.group("file").replace("\\", "/")
            if not traced_file.endswith(TARGET_FILE):
                fail(f"target event came from unexpected file: {traced_file}")
            target_events.append((match.group("event"), raw_line))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    call_count = sum(event == "call" for event, _line in target_events)
    if call_count != 1:
        fail(f"expected exactly one target invocation, found {call_count}")

    exception_payloads = []
    inside_invocation = False
    for event, raw_line in target_events:
        if event == "call":
            inside_invocation = True
        elif inside_invocation and event == "exception":
            exception_match = EXCEPTION_RE.search(raw_line)
            if exception_match is None:
                fail(f"target exception event has no parseable payload: {raw_line}")
            exception_payloads.append(exception_match.group("exc"))
        elif inside_invocation and event == "return":
            inside_invocation = False

    if len(exception_payloads) != 1:
        fail(
            "expected exactly one exception event in the target invocation, "
            f"found {len(exception_payloads)}"
        )

    exception = exception_from_trace(exception_payloads[0])
    exception_type = (
        type(exception).__name__
        if type(exception).__module__ == "builtins"
        else f"{type(exception).__module__}.{type(exception).__qualname__}"
    )
    answer = {
        "exception_message": str(exception),
        "exception_type": exception_type,
    }
    output = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote propagated-exception oracle to {out_path}")


if __name__ == "__main__":
    main()
