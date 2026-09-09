import argparse
import ast
import builtins
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.optimizer.qualify_columns._expand_using"
TARGET_SOURCE = Path("sqlglot/optimizer/qualify_columns.py")
RAISE_LINE = 271
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/qualify_columns\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?P<rest>.*)$"
)
EXCEPTION_RE = re.compile(r"^ exc=(?P<exc>.*?) locals=")

QUESTION = (
    "Run the single pytest test "
    "`sqlglot_qa/qualify_columns_expand_using_s5_exceptions/files/testcase.py::"
    "TestExpandUsingExceptions::test_generated_join_chain_failure`. During that run, "
    "consider invocation 1 of exactly "
    "`sqlglot.optimizer.qualify_columns._expand_using` in "
    "`sqlglot/optimizer/qualify_columns.py`. An invocation means one Python `call` of "
    "exactly that function (excluding its nested local function and all callees), "
    "numbered 1-based in chronological order. What exception is raised by the `raise` "
    "statement beginning at absolute, 1-based source line 271 and propagates out of that "
    "invocation? Here, \"propagates out\" means that the target frame does not handle the "
    "exception and unwinds to its caller; the test's later catch outside the target does "
    "not make it caught inside the target. Line numbers refer to the named file as it "
    "exists in the repository; for a multi-line statement, execution belongs to the line "
    "where the statement or expression begins. Report the exception type using this "
    "convention: bare `type(exc).__name__` for built-in exceptions (for example, "
    "`ValueError`, never `builtins.ValueError`), and `module.QualName` for all others "
    "(for example, `package.errors.CustomError`). Report the message as exact `str(exc)`, "
    "character for character, represented as a JSON string; do not use `repr`, add "
    "quotes to its contents, truncate it, or normalize whitespace. Return exactly a JSON "
    "object with string keys `exception_message` and `exception_type`, each mapped to a "
    "string. No sorting or deduplication applies because the question identifies one "
    "exception from one invocation."
)


def exception_type_name(short_name: str, source_path: Path) -> str:
    builtin = getattr(builtins, short_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return short_name

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for imported in node.names:
                visible_name = imported.asname or imported.name
                if visible_name == short_name:
                    return f"{node.module}.{imported.name}"

    raise RuntimeError(f"cannot resolve non-built-in exception type {short_name!r}")


def exception_message(exception_repr: str, short_name: str) -> str:
    try:
        node = ast.parse(exception_repr, mode="eval").body
    except SyntaxError as error:
        raise RuntimeError(f"cannot parse exception repr: {exception_repr!r}") from error

    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != short_name
        or node.keywords
    ):
        raise RuntimeError(f"unexpected exception repr: {exception_repr!r}")

    args = [ast.literal_eval(argument) for argument in node.args]
    if len(args) == 1:
        return str(args[0])
    return str(tuple(args))


def compute_answer(trace_path: Path) -> dict[str, str]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            target_events.append(match)

    if not target_events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if sum(match.group("event") == "call" for match in target_events) != 1:
        raise RuntimeError("expected exactly one target invocation")

    raised = [
        match
        for match in target_events
        if match.group("event") == "exception"
        and int(match.group("line")) == RAISE_LINE
    ]
    if len(raised) != 1:
        raise RuntimeError(f"expected one exception event at line {RAISE_LINE}")

    exception_index = target_events.index(raised[0])
    later_events = target_events[exception_index + 1 :]
    if not later_events or any(match.group("event") == "line" for match in later_events):
        raise RuntimeError("target frame resumed after the selected exception")
    if later_events[-1].group("event") != "return":
        raise RuntimeError("target frame did not unwind after the selected exception")

    exception_match = EXCEPTION_RE.search(raised[0].group("rest"))
    raw_exception = exception_match.group("exc") if exception_match else None
    if not raw_exception or ": " not in raw_exception:
        raise RuntimeError(f"malformed exception event: {raw_exception!r}")
    short_name, exception_repr = raw_exception.split(": ", 1)

    return {
        "exception_message": exception_message(exception_repr, short_name),
        "exception_type": exception_type_name(short_name, TARGET_SOURCE),
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": compute_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
