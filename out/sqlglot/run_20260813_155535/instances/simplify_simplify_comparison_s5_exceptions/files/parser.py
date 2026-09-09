import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/simplify.py"
TARGET_FUNC = "sqlglot.optimizer.simplify.Simplifier._simplify_comparison"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(
    r"\bexc=(?P<type>[A-Za-z_][A-Za-z0-9_]*): "
    r"(?P<value>.*?) locals="
)

QUESTION = """Run the single pytest test
`sqlglot_qa/simplify_simplify_comparison_s5_exceptions/files/testcase.py::TestSimplifyComparisonExceptions::test_generated_comparisons_then_malformed_number`
against this repository. Across all direct invocations made by that test of
`sqlglot.optimizer.simplify.Simplifier._simplify_comparison`, defined in
`sqlglot/optimizer/simplify.py`, what exception propagates out of the target
function and reaches the test's enclosing exception-catching context?

An invocation is one entry into the original target function body (one Python
function-frame `call`), numbered 1-based in chronological order. Consider only
exceptions raised while that exact target frame is active. An exception is
"caught inside the function" if the target handles it and then executes a
later source-line event in the same invocation. It "propagates out" if it is
not handled by the target, its frame unwinds, and the exception reaches its
caller. Ignore caught exceptions and exceptions confined to other frames. The
test has exactly one exception that meets the propagated-out definition, so
there is no sorting, tie-breaking, or deduplication choice.

Return one JSON object using exactly the canonical shape
`{"exception_message": <string>, "exception_type": <string>}`. The message is
the exact value of `str(exc)`, character for character, without surrounding
`repr` quotes or truncation; normal JSON string escaping applies.

Exception type naming MUST use this convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g. `haystack.core.errors.PipelineError`).
Both output values are strings; neither an absent key, an empty string, nor
JSON `null` represents a missing value."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def exception_message(type_name: str, value_repr: str) -> str:
    try:
        node = ast.parse(value_repr, mode="eval").body
    except SyntaxError as error:
        fail(f"cannot parse exception repr {value_repr!r}: {error}")

    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != type_name
        or node.keywords
    ):
        fail(f"unexpected exception repr shape: {value_repr!r}")

    try:
        args = [ast.literal_eval(argument) for argument in node.args]
    except (ValueError, TypeError) as error:
        fail(f"exception repr has non-literal arguments: {value_repr!r}: {error}")

    exception_class = getattr(builtins, type_name, None)
    if not isinstance(exception_class, type) or not issubclass(exception_class, BaseException):
        fail(f"trace exception is not a built-in exception type: {type_name}")
    return str(exception_class(*args))


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    invocation_count = 0
    line_count = 0
    distinct_lines = set()
    active = False
    pending_exceptions = []
    propagated = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_event_count += 1
        event = match.group("event")
        if event == "call":
            if active:
                fail("overlapping target invocations are not supported")
            invocation_count += 1
            active = True
            pending_exceptions = []
        elif not active:
            fail(f"target {event} event occurred outside an invocation")
        elif event == "line":
            line_count += 1
            distinct_lines.add(int(match.group("line")))
            pending_exceptions = []
        elif event == "exception":
            exception_match = EXCEPTION_RE.search(raw_line)
            if not exception_match:
                fail(f"cannot parse target exception event: {raw_line}")
            pending_exceptions.append(
                (exception_match.group("type"), exception_match.group("value"))
            )
        elif event == "return":
            if pending_exceptions:
                if len(pending_exceptions) != 1:
                    fail("target unwound with multiple unresolved exception events")
                propagated.append(pending_exceptions[0])
            active = False
            pending_exceptions = []

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no invocation of {TARGET_FUNC}")
    if active:
        fail("final target invocation has no matching return/unwind event")
    if line_count < 30 or len(distinct_lines) < 8:
        fail(
            f"target trace is too shallow: {line_count} line events across "
            f"{len(distinct_lines)} distinct lines"
        )
    if len(propagated) != 1:
        fail(f"expected exactly one propagated exception, found {len(propagated)}")

    type_name, value_repr = propagated[0]
    answer = {
        "exception_message": exception_message(type_name, value_repr),
        "exception_type": type_name,
    }
    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} from {invocation_count} target invocations, "
        f"{line_count} line events, and one propagated exception."
    )


if __name__ == "__main__":
    main()
