#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/parsers/earley.py"
TARGET_FUNC = "lark.parsers.earley.Parser.predict_and_complete"
INVOCATION = 59

QUESTION = """Run only the pytest test `lark_qa/earley_predict_and_complete_s1_cfg/files/testcase.py::TestEarleyPredictAndCompleteCFG::test_generated_nested_sequence`. During that test, consider calls to `lark.parsers.earley.Parser.predict_and_complete` as defined in `lark/parsers/earley.py`. What is the exact ordered sequence of executed line events in the function's 59th invocation?

An invocation is one runtime `call` event for exactly that function, counted 1-based in chronological order from the start of this test; calls to any other function do not count. Include only `line` events emitted by that invocation's own frame, from its call until its return. Do not include the `call` or `return` event, and do not include events in callees, comprehensions, or any other frames. Preserve chronological event order exactly, retain repeated line events, and perform no sorting or deduplication.

Line numbers are 1-based physical line numbers in `lark/parsers/earley.py` as it exists in the repository. The function's `def` line, decorator lines, and docstring lines do not appear in the sequence. For a multi-line executable statement, call, or condition, report the line where that statement or expression begins. This target contains no multi-line executable calls or conditions; only its declaration/docstring spans multiple source lines.

Return exactly one JSON object with the shape `{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`. For every element, `file` must be the repo-relative POSIX path `lark/parsers/earley.py`, `func` must be the fully qualified dotted name `lark.parsers.earley.Parser.predict_and_complete` (the general format is `package.module.Class.method`), and `line` must be the integer line number. The list itself is the chronological order defined above; every object has exactly those three keys."""


EVENT_RE = re.compile(
    r"\s(?P<file>\S*lark/parsers/earley\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_invocations(trace_text):
    invocations = []
    current = None
    target_events = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                fail("encountered a nested target call before the prior call returned")
            current = []
        elif event == "line":
            if current is None:
                fail("encountered a target line event outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                fail("encountered a target return event outside an invocation")
            invocations.append(current)
            current = None
        elif event == "exception":
            if current is None:
                fail("encountered a target exception event outside an invocation")

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if current is not None:
        fail("trace ended during an incomplete target invocation")
    return invocations


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

    invocations = parse_invocations(trace_text)
    if len(invocations) <= INVOCATION:
        fail(
            f"need the {INVOCATION}th invocation to be neither last nor absent; "
            f"found {len(invocations)} invocations"
        )

    selected_lines = invocations[INVOCATION - 1]
    if not selected_lines:
        fail(f"invocation {INVOCATION} contains zero line events")

    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
        for line in selected_lines
    ]
    document = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {out_path} with {len(selected_lines)} line events "
        f"from invocation {INVOCATION} of {len(invocations)}"
    )


if __name__ == "__main__":
    main()
