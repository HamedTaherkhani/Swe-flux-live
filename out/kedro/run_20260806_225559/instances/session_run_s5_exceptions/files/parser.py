from __future__ import annotations

import argparse
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/session/session.py"
TARGET_FUNC = "kedro.framework.session.session.run"
RUNNER_CALL_LINE = 409
HANDLER_LINE = 417

EVENT_RE = re.compile(
    r"(?P<file>\S*kedro/framework/session/session\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<type>[A-Za-z_][A-Za-z0-9_]*): .* locals=")

QUESTION = """Run the pytest test
`kedro_qa/session_run_s5_exceptions/files/testcase.py::TestSessionRunExceptions::test_seeded_runner_failures`
and consider every direct invocation it makes of
`kedro.framework.session.session.KedroSession.run` in
`kedro/framework/session/session.py`.

What is the set of exception types caught inside the target function by the
`except Exception as error` handler whose header is on line 417 during the
complete test run? Here, "caught" means an exception raised while evaluating
the `runner.run(...)` call whose multi-line expression begins on line 409 and
then intercepted when control enters that line-417 handler in the same target
frame. Count that exception once as caught even though the handler re-raises
the same object on line 424. Do not include the later propagation to the
test's broad `except`, exceptions handled only in callees, or any exception
that does not enter this specific handler. An invocation is one `call` of the
target function during the test run, numbered from 1 in chronological order;
all invocations count.

Line numbers are absolute, 1-based lines in the named file as it exists in the
repository. For a multi-line statement or expression, line 409 identifies the
executed line where that statement or expression begins. Decorator lines, the
`def` line, and docstring lines do not count as either of the named executed
lines.

Return exactly one JSON object with the shape
`{"caught_exception_kinds": ["..."]}`. The value is a JSON array of strings.
Normalize each caught object's type using this convention: bare
`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never
`builtins.ValueError`), and `module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`), where `module` is
`type(exc).__module__` and `QualName` is `type(exc).__qualname__`. Remove
duplicate normalized strings, then sort the remaining strings in ascending
Unicode code-point order. There is no secondary tie-breaker because equal
normalized strings are deduplicated. Do not use `str()` or `repr()` of the
exception object, and do not report its message. The run is expected to catch
at least one kind, so an empty array, empty string, JSON `null`, or omitted key
does not represent a result."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def normalize_builtin_type(type_name: str) -> str:
    candidate = getattr(builtins, type_name, None)
    if (
        not isinstance(candidate, type)
        or not issubclass(candidate, BaseException)
        or candidate.__module__ != "builtins"
    ):
        fail(
            "Trace exception type cannot be normalized as a built-in type: "
            f"{type_name!r}"
        )
    return candidate.__name__


def harvest(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.is_file():
        fail(f"Trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"Trace log is empty: {trace_path}")

    target_events = 0
    invocation_open = False
    pending_type: str | None = None
    caught_types: list[str] = []

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match or match.group("func") != TARGET_FUNC:
                continue
            if TARGET_FILE not in match.group("file").replace("\\", "/"):
                continue

            target_events += 1
            event = match.group("event")
            line_number = int(match.group("line"))

            if event == "call":
                if invocation_open:
                    fail("Nested target invocation encountered unexpectedly")
                invocation_open = True
                pending_type = None
                continue

            if not invocation_open:
                fail("Encountered a target event before its call event")

            if event == "exception" and line_number == RUNNER_CALL_LINE:
                exception_match = EXCEPTION_RE.search(raw_line)
                if not exception_match:
                    fail(
                        "Could not parse exception payload for runner call: "
                        + raw_line.rstrip()
                    )
                if pending_type is not None:
                    fail("Multiple pending runner exceptions in one invocation")
                pending_type = exception_match.group("type")
                continue

            if event == "line" and line_number == HANDLER_LINE:
                if pending_type is None:
                    fail("Handler entered without a pending runner exception")
                caught_types.append(normalize_builtin_type(pending_type))
                pending_type = None
                continue

            if event == "return":
                if pending_type is not None:
                    fail("Runner exception left target without entering its handler")
                invocation_open = False

    if target_events == 0:
        fail(f"Trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if invocation_open:
        fail("Trace ended before the final target invocation returned")
    if not caught_types:
        fail("No exceptions were caught by the target handler")

    return {"caught_exception_kinds": sorted(set(caught_types))}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle_answer = harvest(args.trace_log)
    document = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
