from __future__ import annotations

import argparse
import builtins
from collections import Counter
import importlib
import json
from pathlib import Path
import re


TARGET_FILE = "scrapy/http/request/form.py"
TARGET_FUNC = "scrapy.http.request.form._get_clickable"

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def exception_subclasses(cls: type[BaseException]) -> set[type[BaseException]]:
    found: set[type[BaseException]] = set()
    pending = [cls]
    while pending:
        parent = pending.pop()
        for child in parent.__subclasses__():
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def canonical_exception_name(simple_name: str) -> str:
    builtin = getattr(builtins, simple_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return simple_name

    # Load the extension that can raise while evaluating FormElement XPath.
    importlib.import_module("lxml.etree")
    matches = {
        (candidate.__module__, candidate.__qualname__)
        for candidate in exception_subclasses(BaseException)
        if candidate.__name__ == simple_name
    }
    if len(matches) != 1:
        fail(
            f"cannot uniquely resolve non-built-in exception {simple_name!r}; "
            f"candidates={sorted(matches)!r}"
        )
    module, qualname = matches.pop()
    return f"{module}.{qualname}"


def parse_exception_counts(trace_path: Path) -> list[dict[str, int | str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    raw_counts: Counter[str] = Counter()
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_event_count += 1
        if match.group("event") != "exception":
            continue
        exception_match = EXCEPTION_RE.search(raw_line, match.end())
        if not exception_match:
            fail(f"cannot parse target exception event: {raw_line}")
        raw_counts[exception_match.group("name")] += 1

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not raw_counts:
        fail(f"trace contains no exception observations for {TARGET_FUNC}")

    canonical_counts: Counter[str] = Counter()
    for simple_name, count in raw_counts.items():
        canonical_counts[canonical_exception_name(simple_name)] += count
    return [
        {"count": canonical_counts[name], "exception_type": name}
        for name in sorted(canonical_counts)
    ]


def question_text() -> str:
    return (
        "Run every pytest test method in "
        "`scrapy_qa/form_get_clickable_m5_exceptions/files/testcase.py::"
        "TestGetClickableExceptions` (all methods whose names begin with `test_`). "
        "Pytest identifies a method by the class node id followed by its method, for "
        "example "
        "`scrapy_qa/form_get_clickable_m5_exceptions/files/testcase.py::"
        "TestGetClickableExceptions::test_hypothetical_case`. Aggregate the answer "
        "over ALL such methods; pytest collects these `unittest.TestCase` methods in "
        "ascending lexicographic method-name order, with no ordering tie-breaker "
        "because their names are unique. During that complete run, consider every "
        "invocation of `scrapy.http.request.form._get_clickable` in "
        "`scrapy/http/request/form.py`. An invocation is one call of that exact "
        "function, numbered 1-based in chronological execution order, although "
        "invocation numbers are not output. Count an exception observation whenever "
        "Python reports an exception event in that exact target frame: this includes "
        "an exception raised by code in the frame and an exception propagated into "
        "the frame from a callee. Count each target-frame observation once, including "
        "exceptions that the target subsequently handles. An exception raised and "
        "fully handled inside a callee does not count because it never produces an "
        "observation in the target frame. If the same exception object is re-raised "
        "in the target frame, count that re-raise again as a separate observation. "
        "Counts are totals over ALL invocations and ALL test methods, so repeated "
        "observations of the same type in one or several methods all contribute. "
        "Exception type naming uses bare `type(exc).__name__` for built-ins (e.g. "
        "`ValueError`, never `builtins.ValueError`), `module.QualName` for all "
        "others. Message = exact `str(exc)`. Messages are not included in this "
        "answer. Combine all observations having the same formatted exception type "
        "into one object; do not otherwise deduplicate observations. Return exactly "
        "one JSON object with the key `exception_type_counts`. Its value is a JSON "
        "array of objects, each with exactly `count` (a JSON integer) and "
        "`exception_type` (a JSON string). Include every type observed at least once "
        "and no zero-count entries. Sort the array by `exception_type` ascending in "
        "Unicode code-point lexicographic order. Equal exception-type names have "
        "already been combined, so no secondary tie-breaker is needed. Do not include "
        "messages, test ids, invocation numbers, line numbers, null placeholders, or "
        "additional keys."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = {
        "exception_type_counts": parse_exception_counts(Path(args.trace_log))
    }
    payload = {
        "question_kind": "M5_Exceptions",
        "question": question_text(),
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
