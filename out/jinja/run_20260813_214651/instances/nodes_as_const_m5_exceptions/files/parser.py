#!/usr/bin/env python3
"""Parse trace logs for _FilterTestCommon.as_const exception observations."""

from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/nodes.py"
TARGET_FUNC = "jinja2.nodes._FilterTestCommon.as_const"

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)
EXC_RE = re.compile(r"exc=(?P<exc>[^:]+)(?:: (?P<msg>.*))?\s+locals=")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _resolve_exception_type(class_name: str) -> str:
    obj = getattr(builtins, class_name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return class_name

    nodes = importlib.import_module("jinja2.nodes")
    obj = getattr(nodes, class_name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return f"jinja2.nodes.{class_name}"

    raise SystemExit(f"Could not resolve exception class name: {class_name}")


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def _parse_exception_name(exc_field: str) -> str:
    class_name = exc_field.strip()
    if not class_name:
        raise SystemExit("Empty exception class name in trace event")
    return _resolve_exception_type(class_name)


def harvest_exception_counts(trace_log: Path) -> dict[str, int]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    counts: dict[str, int] = {}
    target_events = 0

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        if parsed["event"] != "exception":
            continue

        exc_match = EXC_RE.search(raw_line)
        if exc_match is None:
            raise SystemExit(f"Malformed exception trace line: {raw_line}")

        exc_type = _parse_exception_name(exc_match.group("exc"))
        counts[exc_type] = counts.get(exc_type, 0) + 1

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if not counts:
        raise SystemExit(
            f"Trace contains {target_events} target events but zero exception events"
        )

    return counts


def build_question() -> str:
    return (
        "Consider every test method in "
        "`jinja_qa/nodes_as_const_m5_exceptions/files/testcase.py::"
        "TestNodesAsConstExceptionAggregation`. The answer aggregates behavior "
        "across **all** `test_*` methods in that class, in the chronological "
        "order pytest collects and runs them (definition order in the file). "
        "Each method is identified by its pytest node id, e.g. "
        "`jinja_qa/nodes_as_const_m5_exceptions/files/testcase.py::"
        "TestNodesAsConstExceptionAggregation::test_compile_odd_sweep`.\n\n"
        "Those tests reach `jinja2.nodes._FilterTestCommon.as_const` in "
        f"`{TARGET_FILE}` only **indirectly**: through template compilation "
        "(optimizer and compiler constant-folding paths) and through caller "
        "node `as_const` methods such as `jinja2.nodes.And.as_const`, "
        "`jinja2.nodes.Compare.as_const`, and `jinja2.nodes.CondExpr.as_const` "
        "on parsed template expressions — never by importing or calling "
        "`_FilterTestCommon.as_const` directly.\n\n"
        "Target function: `jinja2.nodes._FilterTestCommon.as_const` "
        f"(the method beginning at line 746 of `{TARGET_FILE}`).\n\n"
        "**Exception type naming** uses bare `type(exc).__name__` for built-in "
        "exceptions (e.g. `ValueError`, never `builtins.ValueError`) and "
        "`module.QualName` for all other exception classes (e.g. "
        "`jinja2.nodes.Impossible`).\n\n"
        "**Observation rule**: count one observation each time an exception "
        "is observed in the `_FilterTestCommon.as_const` frame during the test "
        "run — either raised directly in that frame or propagated into that "
        "frame from a callee before any handler in that frame catches it. "
        "Exceptions raised and fully handled inside a callee without entering "
        "the target frame do not count. If the same exception object is "
        "re-raised in the same target frame after being caught there, that "
        "second observation counts again; propagation from a callee into the "
        "target frame and a subsequent `raise` of a new exception in the "
        "target frame are separate observations.\n\n"
        "**Counting**: totals over **all** invocations of "
        "`_FilterTestCommon.as_const` and **all** test methods in the class; "
        "the same exception type raised in five methods contributes five to "
        "that type's total (plus any additional observations within each "
        "invocation).\n\n"
        "Return JSON with the single top-level key `exception_type_counts`: "
        "a list of objects, each with keys `exception_type` (string) and "
        "`count` (non-negative integer). Include every exception type observed "
        "at least once. Sort the list by `exception_type` ascending; when "
        "types tie (they cannot), break ties by `count` ascending."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    counts = harvest_exception_counts(args.trace_log)

    oracle_answer = {
        "exception_type_counts": [
            {"count": counts[name], "exception_type": name}
            for name in sorted(counts)
        ]
    }
    template_answer = {
        "exception_type_counts": [{"count": "int", "exception_type": "str"}]
    }

    payload = {
        "question_kind": "M5_Exceptions",
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
