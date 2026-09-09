#!/usr/bin/env python3
import argparse
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "haystack/components/routers/file_type_router.py"
TRACE_FUNC = "haystack.components.routers.file_type_router.run"
EVENT_RE = re.compile(
    rf"(?P<file>\S*{re.escape(TARGET_FILE)}):(?P<line>\d+) "
    rf"(?P<func>{re.escape(TRACE_FUNC)}) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bevent=exception exc=(?P<kind>[A-Za-z_][A-Za-z0-9_]*): ")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_events(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        event: dict[str, object] = {
            "line": int(match.group("line")),
            "event": match.group("event"),
            "raw": raw_line,
        }
        if match.group("event") == "exception":
            exception_match = EXCEPTION_RE.search(raw_line)
            if not exception_match:
                fail(f"could not parse target exception event: {raw_line}")
            event["kind"] = exception_match.group("kind")
        events.append(event)

    if not events:
        fail(f"trace contains zero events for {TRACE_FUNC}")
    return events


def builtin_exception_name(raw_name: str) -> str:
    candidate = getattr(builtins, raw_name, None)
    if not isinstance(candidate, type) or not issubclass(candidate, BaseException):
        fail(
            "encountered a non-built-in exception whose qualified name is not "
            f"recoverable from this trace format: {raw_name}"
        )
    return candidate.__name__


def caught_exception_kinds(events: list[dict[str, object]]) -> list[str]:
    call_count = sum(event["event"] == "call" for event in events)
    if call_count != 1:
        fail(f"expected exactly one target invocation, found {call_count}")

    caught: set[str] = set()
    pending_kind: str | None = None
    entered_handler = False

    for event in events:
        event_name = event["event"]
        line = event["line"]

        if event_name == "exception" and line == 184:
            if pending_kind is not None:
                fail("a new conversion exception occurred before the prior one was classified")
            pending_kind = builtin_exception_name(str(event["kind"]))
            entered_handler = False
        elif pending_kind is not None and event_name == "line" and line == 185:
            entered_handler = True
        elif pending_kind is not None and event_name == "line" and line == 188:
            if not entered_handler:
                fail("handler body was reached without observing its entry line")
            caught.add(pending_kind)
            pending_kind = None
            entered_handler = False
        elif pending_kind is not None and event_name == "return":
            fail(f"exception propagated instead of being caught: {pending_kind}")

    if pending_kind is not None:
        fail(f"trace ended before exception was classified: {pending_kind}")
    if not caught:
        fail("no exceptions caught by the target handler were found")
    return sorted(caught)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    events = parse_events(Path(args.trace_log))
    answer = {"caught_exception_kinds": caught_exception_kinds(events)}
    question = (
        "Run the single pytest method "
        "`haystack_qa/file_type_router_run_s5_exceptions/files/testcase.py::"
        "TestFileTypeRouterRunExceptions::test_catches_generated_conversion_failures`. "
        "During its single invocation of "
        "`haystack.components.routers.file_type_router.FileTypeRouter.run` in "
        "`haystack/components/routers/file_type_router.py`, which distinct exception "
        "types are caught by the `except Exception as e` handler that begins at "
        "absolute, 1-based line 185? An invocation means one call of that target "
        "function during the test run; invocation numbering is 1-based in chronological "
        "order, and this question covers invocation 1. Count an exception as caught "
        "only when evaluation of the call whose expression begins at absolute, 1-based "
        "line 184 raises into the target's own frame and execution then enters the "
        "handler at line 185 and reaches the handler body at line 188, rather than the "
        "exception propagating out of the target. Line numbers refer to the named file "
        "as it exists in the repository; for a multi-line statement, use the line where "
        "the statement or expression begins. Decorator, `def`, and docstring lines do "
        "not count unless they execute during this invocation. Remove duplicate type "
        "names across all qualifying events, then sort the remaining strings in "
        "ascending lexicographic order by Unicode code point, with no secondary "
        "tie-breaker needed after deduplication. Exception type naming MUST use this "
        "convention: bare `type(exc).__name__` for built-in exceptions (e.g. "
        "`ValueError` — never `builtins.ValueError`), and `module.QualName` for all "
        "others (e.g. `haystack.core.errors.PipelineError`). Return exactly one JSON "
        "object with key `caught_exception_kinds`; its value is the sorted JSON array "
        "of strings just defined. Do not report exception messages, counts, or repeated "
        "occurrences."
    )
    payload = {
        "question_kind": "S5_Exceptions",
        "question": question,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
