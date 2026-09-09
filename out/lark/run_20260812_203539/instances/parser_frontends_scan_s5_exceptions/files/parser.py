#!/usr/bin/env python3
import argparse
import builtins
import json
import re
import sys
from pathlib import Path

import lark.exceptions


TARGET_FILE = "lark/parser_frontends.py"
TARGET_FUNC = "lark.parser_frontends.ParsingFrontend._scan"
TEST_MODULE = "testcase"
CAUGHT_HANDLER_BODY_LINES = {206, 211, 217}
RERAISE_LINE = 214

QUESTION = """Run only the pytest test `lark_qa/parser_frontends_scan_s5_exceptions/files/testcase.py::TestParsingFrontendScanExceptions::test_generated_mixed_candidates`. Across the complete execution of that one test method, what set of concrete exception types is caught inside `lark.parser_frontends.ParsingFrontend._scan`, defined in `lark/parser_frontends.py`, by the `except UnexpectedInput` handlers at lines 205 and 209 or the `except ValueError` handler at line 215?

“Caught inside” means that an exception raised while evaluating one of this function's try suites propagates into the target function's own frame and control then enters the matching handler body (line 206, 211, or 217). Include the concrete runtime type of that exception object, including exceptions originating in callees or iterator advancement. Exclude exceptions raised and handled wholly in callees, exceptions that propagate out of `_scan`, and the `ConfigurationError` path re-raised at line 214. Aggregate all executions and generator resumptions of exactly this target function during the named test. Treat the answer as a set: remove duplicate type names, even when a type is caught repeatedly.

Exception type naming MUST use this convention: bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and `module.QualName` for all others (e.g. `haystack.core.errors.PipelineError`). Use the concrete exception object's type, not the class named by the matching `except` clause. Sort the deduplicated names in ascending lexicographic order by Unicode code point; there are no secondary tie-breakers because duplicates are removed.

Return exactly one JSON object with the shape `{"caught_exception_kinds": ["str"]}`. The value is a JSON array of the sorted strings defined above; emit no extra keys. Line numbers above are absolute 1-based physical lines in `lark/parser_frontends.py` as it exists in the repository. For a multi-line statement or expression, its executed line is the line where that statement or expression begins; decorator, `def`, and docstring lines are not relevant to identifying these handlers."""

EVENT_RE = re.compile(
    r"\s(?P<file>\S*lark/parser_frontends\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r"(?:\s+exc=(?P<exc_type>[A-Za-z_][A-Za-z0-9_]*):)?"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def qualified_exception_name(type_name):
    builtin = getattr(builtins, type_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return type_name

    lark_type = getattr(lark.exceptions, type_name, None)
    if isinstance(lark_type, type) and issubclass(lark_type, BaseException):
        return f"{lark_type.__module__}.{lark_type.__qualname__}"

    return f"{TEST_MODULE}.{type_name}"


def caught_exception_types(trace_text):
    caught = set()
    pending_type = None
    target_events = 0
    exception_events = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "exception":
            exception_events += 1
            pending_type = match.group("exc_type")
            if not pending_type:
                fail(f"could not parse exception type from trace line: {raw_line}")
        elif event == "line" and pending_type is not None:
            if line in CAUGHT_HANDLER_BODY_LINES:
                caught.add(qualified_exception_name(pending_type))
                pending_type = None
            elif line == RERAISE_LINE:
                pending_type = None
        elif event == "return" and pending_type is not None:
            pending_type = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if exception_events == 0:
        fail(f"trace contains zero exception events for {TARGET_FUNC}")
    if not caught:
        fail(f"trace contains no exceptions caught inside {TARGET_FUNC}")
    return sorted(caught)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    kinds = caught_exception_types(trace_text)
    document = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": kinds},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out_path} with {len(kinds)} caught exception kinds")


if __name__ == "__main__":
    main()
