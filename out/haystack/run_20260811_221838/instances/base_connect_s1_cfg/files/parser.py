#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/core/pipeline/base.py"
TARGET_FUNC = "haystack.core.pipeline.base.PipelineBase.connect"
TRACE_FUNC = "haystack.core.pipeline.base.connect"
INVOCATION = 10

QUESTION = """Run only the pytest test
`haystack_qa/base_connect_s1_cfg/files/testcase.py::TestIndirectDenseConnections::test_loads_generated_pipeline`
against this repository. During that test, consider invocations of
`haystack.core.pipeline.base.PipelineBase.connect` whose code is in
`haystack/core/pipeline/base.py`. An invocation is one `call` event for that
exact function frame; number invocations 1-based in chronological call-event
order during the test. What is the exact ordered sequence of executed line
events inside the 10th invocation?

Return exactly one JSON object with the key `executed_path`, whose value is a
list of objects. Every list object must have exactly these keys:
`file` (string), `func` (string), and `line` (integer). Use the repo-relative
POSIX path `haystack/core/pipeline/base.py` for `file`, and use the fully
qualified dotted module-and-qualname
`haystack.core.pipeline.base.PipelineBase.connect` for `func`. `line` is the
absolute 1-based physical line number in that file as it exists in the
repository.

An executed line event means a CPython `line` event emitted by the exact
`PipelineBase.connect` frame: include only `line` events from that frame, not
its `call`, `return`, or `exception` events and not events in callees,
comprehension frames, or any other frame. Preserve chronological event order
and preserve every repeated line event; do not sort or deduplicate. The
function's `def` line, decorator lines, and docstring-only lines do not appear
in the sequence. This function contains multi-line calls and conditions: a
multi-line statement is associated with the physical line where the statement
begins, while a separately evaluated continuation expression that CPython
reports with its own `line` event remains a separate event at that reported
physical line."""


EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_executed_path(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_path = match.group("path").replace("\\", "/")
        if not normalized_path.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TRACE_FUNC:
            continue
        target_events.append(
            (match.group("event"), int(match.group("line")))
        )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    invocation_number = 0
    collecting = False
    completed = False
    executed_lines: list[int] = []
    for event, line_number in target_events:
        if event == "call":
            invocation_number += 1
            collecting = invocation_number == INVOCATION
            if collecting:
                executed_lines = []
            continue
        if not collecting:
            continue
        if event == "line":
            executed_lines.append(line_number)
        elif event == "return":
            collecting = False
            completed = True
            break

    if invocation_number < INVOCATION:
        fail(
            f"trace has only {invocation_number} invocation(s) of {TARGET_FUNC}; "
            f"invocation {INVOCATION} is required"
        )
    if not completed:
        fail(f"invocation {INVOCATION} has no return event")
    if not executed_lines:
        fail(f"invocation {INVOCATION} contains zero line events")

    return [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line_number}
        for line_number in executed_lines
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": parse_executed_path(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
