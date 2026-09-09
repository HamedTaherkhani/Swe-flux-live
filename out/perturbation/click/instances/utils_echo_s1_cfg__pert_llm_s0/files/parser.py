from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/utils.py"
TARGET_FUNC = "click.utils.echo"
INVOCATION_NUMBER = 17

QUESTION = """Run only the pytest test `click_qa/utils_echo_s1_cfg/files/testcase.py::EchoGeneratedControlFlow::test_seeded_message_and_stream_matrix`. During that test, consider invocations of exactly `click.utils.echo` in `src/click/utils.py`. An invocation is one runtime `call` entry into that exact function frame, counted 1-based in chronological order during the test; calls to other functions or methods, including functions called by `echo`, do not count as invocations. What is the exact ordered sequence of executed line events inside the 17th invocation?

Include only `line` events emitted while the 17th target frame is active. Exclude its `call`, `return`, and `exception` events, and exclude every event in caller, callee, generator, and comprehension frames. Preserve chronological execution order exactly, retain every repeated line event (including consecutive duplicates), and perform no sorting or deduplication.

Source line numbers are absolute, 1-based physical line numbers in `src/click/utils.py` as it exists in the repository for this run. The function's `def` line does not appear in the sequence because the call-entry event is excluded. Decorator lines (there are none on this function), blank lines, comment-only lines, and docstring-only lines do not appear. If an executable statement, condition, or call spans multiple physical lines, report its line event at the physical line where that statement, condition, or call begins.

Return exactly one JSON object with the shape `{"executed_path": [{"file": <str>, "func": <str>, "line": <int>}, ...]}` and no additional keys. `executed_path` is a JSON array in the chronological order defined above. Every element must contain exactly these keys in this order: `file`, `func`, `line`. For every element, `file` is the JSON string `src/click/utils.py`, `func` is the fully qualified `module.qualname` JSON string `click.utils.echo` (the naming format is like `acme.tools.Widget.run`, not a bare function name), and `line` is the unquoted JSON integer for the executed source line. The strings are literal names, not `repr()` or `str()` renderings, and there is no null or other empty-value sentinel."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_executed_path(trace_path: Path) -> list[dict[str, str | int]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    invocations: list[list[int]] = []
    active_invocation: int | None = None
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue

        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")

        if event == "call":
            if active_invocation is not None:
                fail("overlapping target invocations are not supported")
            invocations.append([])
            active_invocation = len(invocations) - 1
        elif event == "line":
            if active_invocation is None:
                fail("target line event occurred outside an active invocation")
            invocations[active_invocation].append(int(match.group("line")))
        elif event == "return":
            if active_invocation is None:
                fail("target return event occurred outside an active invocation")
            active_invocation = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if active_invocation is not None:
        fail("trace ended before the final target invocation returned")
    if len(invocations) < INVOCATION_NUMBER:
        fail(
            f"trace contains only {len(invocations)} target invocations; "
            f"cannot select invocation {INVOCATION_NUMBER}"
        )

    selected_lines = invocations[INVOCATION_NUMBER - 1]
    if not selected_lines:
        fail(f"invocation {INVOCATION_NUMBER} contains zero line events")

    return [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
        for line in selected_lines
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        document = {
            "question_kind": "S1_IntraProceduralCFG",
            "question": QUESTION,
            "template_answer": {
                "executed_path": [
                    {"file": "str", "func": "str", "line": "int"}
                ]
            },
            "oracle_answer": {
                "executed_path": parse_executed_path(args.trace_log)
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(document, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: failed to build control-flow oracle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
