import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/json/provider.py"
TARGET_FUNC = "flask.json.provider._default"
INVOCATION = 9

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`flask_qa/provider_default_s1_cfg/files/testcase.py::TestProviderDefault::test_dynamic_extent_path`.
Consider calls to `flask.json.provider._default` whose code is in
`src/flask/json/provider.py`. An invocation is one Python `call` event for
exactly that function, counted 1-based in chronological event order across
the whole test; calls made re-entrantly from another `_default` invocation
count as separate invocations in that same chronology.

For the 9th invocation, report `executed_path`: the exact chronological
sequence of Python `line` events for exactly
`flask.json.provider._default` during the selected invocation's dynamic
extent. The dynamic extent starts immediately after that invocation's
`call` event and ends at its matching `return` event. Include line events
from any nested or re-entrant invocations of that exact function that occur
before the selected frame returns. Exclude all `call`, `return`, and
`exception` events, and exclude events from every other function and file.

Preserve runtime event order exactly; do not sort, group, or remove
duplicates. If two consecutive events have the same line, retain both in
their original order. For each event emit an object with exactly `file`
(string), `func` (string), and `line` (integer). Set `file` to the
repo-relative string `src/flask/json/provider.py`, set `func` to the fully
qualified Python name `flask.json.provider._default`, and use absolute,
1-based source line numbers in that file as it exists in the repository.
The function's `def` line is represented by its `call` event and therefore
does not appear in this line-event sequence; decorator and docstring lines
would appear only if Python emitted `line` events for them. For a
multi-line statement, call, or condition, record the line reported by
Python, which is normally the line where the currently executed
statement or expression begins.

Return exactly the JSON object shape
`{"executed_path": [{"file": string, "func": string, "line": integer}, ...]}`.
The array order is the chronological order defined above, with duplicates
retained; there are no additional keys and no value stringification rules
because line numbers remain JSON integers."""


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_events(trace_path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        absolute_file = match.group("file").replace("\\", "/")
        if not absolute_file.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append(
            {
                "event": match.group("event"),
                "line": int(match.group("line")),
            }
        )

    if not events:
        fail(
            "trace log contains zero events for "
            f"{TARGET_FUNC} in {TARGET_FILE}"
        )
    return events


def selected_dynamic_extent(events):
    calls_seen = 0
    selected = False
    depth = 0
    path = []

    for event in events:
        kind = event["event"]
        if kind == "call":
            calls_seen += 1
            if selected:
                depth += 1
            elif calls_seen == INVOCATION:
                selected = True
                depth = 1
            continue

        if not selected:
            continue

        if kind == "line":
            path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": event["line"],
                }
            )
        elif kind == "return":
            depth -= 1
            if depth == 0:
                break

    if calls_seen < INVOCATION:
        fail(
            f"expected at least {INVOCATION} target invocations, "
            f"found {calls_seen}"
        )
    if selected and depth != 0:
        fail("selected invocation has no matching return event")
    if not path:
        fail("selected invocation produced no line events")
    return path


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    answer = {"executed_path": selected_dynamic_extent(parse_events(args.trace_log))}
    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
