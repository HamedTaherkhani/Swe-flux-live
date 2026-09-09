#!/usr/bin/env python3
"""Parse trace log for S5_Exceptions oracle (propagated exception)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/style.py"
TARGET_FUNC = "rich.style.Style.parse"
TARGET_FUNC_SUFFIX = "Style.parse"

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>.+?))?"
    r"(?: locals=.*)?$"
)

QUESTION = (
    "For pytest test "
    "`rich_qa/style_parse_s5_exceptions/files/testcase.py::"
    "TestStyleNormalizeIndirectParse::test_normalize_programmatic_style_specs`, "
    f"consider `{TARGET_FUNC}` in `{TARGET_FILE}` during that test run.\n\n"
    "Invocation counting: an invocation is one `call` event for this qualname, "
    "numbered chronologically from 1 in the order those `call` events appear "
    "during the test.\n\n"
    "The answer covers the invocation triggered when the test calls "
    "`Style.normalize` on the style specification inserted at the computed "
    "`fault_index` position in the test's `specs` list (0-based index). "
    "That invocation does not complete with a `return` event; an exception "
    "propagates out of `Style.parse` to its caller.\n\n"
    "Report the propagated exception's type and message:\n"
    "- `exception_type`: use bare `type(exc).__name__` for built-in exceptions "
    "(for example `ValueError`, never `builtins.ValueError`), and "
    "`module.QualName` for all others (for example `rich.errors.StyleSyntaxError`).\n"
    "- `exception_message`: the exact `str(exc)` value, character for character.\n\n"
    "Propagated exception: among `exception` events recorded for that "
    "invocation, take the last one — that is the exception instance that "
    "leaves `Style.parse` uncaught."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC or func.endswith(TARGET_FUNC_SUFFIX)


def _parse_trace(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log empty: {path}")

    events: list[dict] = []
    for raw in text.splitlines():
        m = TRACE_RE.match(raw)
        if not m:
            continue
        if TARGET_FILE not in m.group("file").replace("\\", "/"):
            continue
        func = m.group("func")
        if not _func_matches(func):
            continue
        events.append(
            {
                "lineno": int(m.group("lineno")),
                "func": func,
                "event": m.group("event"),
                "exc": m.group("exc"),
            }
        )
    return events


def _split_invocations(events: list[dict]) -> list[list[dict]]:
    invocations: list[list[dict]] = []
    current: list[dict] = []
    for event in events:
        if event["event"] == "call":
            if current:
                invocations.append(current)
            current = [event]
        else:
            if current:
                current.append(event)
    if current:
        invocations.append(current)
    return invocations


def _builtin_type_name(exc_type_name: str) -> bool:
    import builtins

    return hasattr(builtins, exc_type_name) and exc_type_name.isidentifier()


def _format_exception_type(exc_type_name: str) -> str:
    if _builtin_type_name(exc_type_name):
        return exc_type_name
    if exc_type_name == "StyleSyntaxError":
        return "rich.errors.StyleSyntaxError"
    if exc_type_name == "ColorParseError":
        return "rich.color.ColorParseError"
    raise SystemExit(f"Unhandled exception type in trace: {exc_type_name}")


def _message_from_exc_field(exc_field: str) -> tuple[str, str]:
    if ": " not in exc_field:
        raise SystemExit(f"Malformed exc field: {exc_field!r}")
    type_name, repr_part = exc_field.split(": ", 1)
    type_name = type_name.strip()
    repr_part = repr_part.strip()
    if "(" not in repr_part or not repr_part.endswith(")"):
        raise SystemExit(f"Unexpected exception repr in trace: {repr_part!r}")
    open_paren = repr_part.index("(")
    inner = repr_part[open_paren + 1 : -1]
    message = ast.literal_eval(inner)
    if not isinstance(message, str):
        raise SystemExit(f"Expected string exception message, got {message!r}")
    return type_name, message


def _propagated_exception(invocation: list[dict]) -> tuple[str, str] | None:
    if any(event["event"] == "return" for event in invocation):
        return None
    exc_events = [event for event in invocation if event["event"] == "exception"]
    if not exc_events:
        return None
    last = exc_events[-1]
    if not last.get("exc"):
        raise SystemExit("Exception event missing exc= payload")
    type_name, message = _message_from_exc_field(last["exc"])
    return _format_exception_type(type_name), message


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    invocations = _split_invocations(events)
    if not invocations:
        raise SystemExit(f"No invocations found for {TARGET_FUNC}")

    propagated: list[tuple[str, str]] = []
    for invocation in invocations:
        result = _propagated_exception(invocation)
        if result is not None:
            propagated.append(result)

    if len(propagated) != 1:
        raise SystemExit(
            f"Expected exactly one invocation with a propagated exception, "
            f"found {len(propagated)}"
        )

    exception_type, exception_message = propagated[0]
    oracle_answer = {
        "exception_type": exception_type,
        "exception_message": exception_message,
    }
    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
