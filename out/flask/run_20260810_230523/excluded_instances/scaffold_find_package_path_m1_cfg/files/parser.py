#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/flask/sansio/scaffold.py"
TARGET_FUNC = "flask.sansio.scaffold._find_package_path"

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/scaffold_find_package_path_m1_cfg/files/testcase.py::"
    "FindPackagePathControlFlowTest::test_generated_import_layouts`. During "
    "that entire test run, consider every invocation of exactly "
    "`flask.sansio.scaffold._find_package_path` in the repo-relative file "
    "`src/flask/sansio/scaffold.py`, including the function's lexically nested "
    "generator-expression frame. An invocation means one runtime call event "
    "for the exact function, numbered 1-based in chronological order; the "
    "number is only a definition and is not part of the answer. Report the "
    "union of source lines that produce a Python runtime `line` event in those "
    "frames across all invocations. Count only `line` events, not `call`, "
    "`return`, or `exception` events, and do not count events from callees or "
    "any other frames. The function's `def` line and decorator lines do not "
    "count because invoking the function does not produce a `line` event for "
    "them; a docstring line counts only if Python emits a runtime `line` event "
    "for it. Line numbers are absolute, 1-based source line numbers in the "
    "named file as it exists in the repository. For a multi-line statement or "
    "expression, use the physical line attached to each runtime `line` event, "
    "that is, the line where the executed statement or expression component "
    "begins; a visual continuation line with no event is not inferred. For "
    "example, events on lines 3 and 8 are represented as JSON integers in "
    "`[3, 8]`. Deduplicate line numbers across repeated events, nested-frame "
    "resumptions, and invocations, then sort them in strictly ascending "
    "numeric order. Return exactly one JSON object with the sole key "
    "`covered_lines`; its value is that sorted JSON array of integers. No "
    "`repr` or `str` conversion is applied."
)

EVENT_RE = re.compile(
    r"(?P<file>\S*src/flask/sansio/scaffold\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> list[int]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events: list[tuple[int, str, str]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)

        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")
        function_name = match.group("func")

        if not file_name.endswith(TARGET_FILE):
            continue

        if function_name in {
            TARGET_FUNC,
            f"{TARGET_FUNC}.<locals>.<genexpr>",
        }:
            target_events.append(
                (
                    int(match.group("line")),
                    function_name,
                    match.group("event"),
                )
            )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    call_count = sum(
        event == "call" and function_name == TARGET_FUNC
        for _, function_name, event in target_events
    )

    if call_count < 3:
        fail(f"expected at least three target invocations, found {call_count}")

    covered_lines = sorted(
        {
            line_number
            for line_number, _, event in target_events
            if event == "line"
        }
    )

    if not covered_lines:
        fail("target trace contains no runtime line events")

    return covered_lines


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    covered_lines = parse_trace(args.trace_log)
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
