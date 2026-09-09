#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/cli/config/init.py"
TARGET_FUNC = "instructlab.cli.config.init.get_params"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> list[int]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    total_line_events = 0
    invocations: list[list[int]] = []
    active: list[int] | None = None

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if active is not None:
                fail("encountered a nested target call before the prior invocation ended")
            active = []
            invocations.append(active)
        elif event == "line":
            if active is None:
                fail("encountered a target line event outside an invocation")
            active.append(int(match.group("line")))
            total_line_events += 1
        elif event == "return":
            if active is None:
                fail("encountered a target return event outside an invocation")
            active = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active is not None:
        fail("trace ended while a target invocation was active")
    if len(invocations) < 3:
        fail(f"expected at least 3 target invocations, found {len(invocations)}")
    if any(not invocation for invocation in invocations):
        fail("one or more target invocations contains zero line events")
    distinct_paths = {tuple(sorted(set(invocation))) for invocation in invocations}
    if len(distinct_paths) < 3:
        fail(f"expected at least 3 distinct invocation paths, found {len(distinct_paths)}")
    if total_line_events < 60:
        fail(f"expected at least 60 target line events, found {total_line_events}")

    covered_lines = sorted(
        {line_number for invocation in invocations for line_number in invocation}
    )
    if len(covered_lines) < 25:
        fail(f"expected at least 25 covered target lines, found {len(covered_lines)}")
    return covered_lines


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    covered_lines = parse_trace(Path(args.trace_log))
    question = (
        "Run the single pytest test "
        "`instruct_lab_qa/init_get_params_m1_cfg/files/testcase.py::"
        "TestInitParameterPaths::test_command_routes_four_taxonomy_scenarios` "
        "against this repository. Across the whole test, what is the exact line "
        "coverage of `instructlab.cli.config.init.get_params` in "
        "`src/instructlab/cli/config/init.py`? An invocation means one runtime "
        "`call` event for exactly this function, numbered 1-based in chronological "
        "order. Compute the union of runtime `line` events from every invocation "
        "during the test, including an invocation that exits by propagating an "
        "exception. Count an event only when its active frame is exactly "
        "`instructlab.cli.config.init.get_params`; exclude call, return, and "
        "exception events and all events in callers, callees, nested functions, "
        "and other frames. Report absolute 1-based physical line numbers in the "
        "named repository file as it exists during the test. A runtime line event "
        "uses Python's `frame.f_lineno`: for a multi-line statement or expression, "
        "include each physical line for which Python actually emits a line event, "
        "without normalizing continuation lines to the statement's first line or "
        "inferring execution merely because source text spans a line. The "
        "function's `def` line is represented by the call event and does not "
        "count; parameter-continuation lines, decorator lines, comments, blank "
        "lines, and docstring lines count only if they independently produce a "
        "runtime line event (this function has no decorators or docstring). Return "
        "exactly one JSON object with the single key `covered_lines`. Its value "
        "must be a JSON array of JSON integers containing all qualifying line "
        "numbers in strictly ascending numeric order, deduplicated both within "
        "and across invocations. For example, hypothetical events on lines 9, 4, "
        "and 9 serialize as `{\"covered_lines\":[4,9]}` (JSON whitespace is "
        "insignificant). Do not encode numbers as strings, and do not use Python "
        "`repr`, JSON null, empty-string sentinels, or omitted values."
    )
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": question,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
