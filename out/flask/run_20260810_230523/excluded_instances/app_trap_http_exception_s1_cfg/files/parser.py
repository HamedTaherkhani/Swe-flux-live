import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/sansio/app.py"
TARGET_FUNC = "flask.sansio.app.App.trap_http_exception"
INVOCATION = 32

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`flask_qa/app_trap_http_exception_s1_cfg/files/testcase.py::TestTrapHTTPException::test_reentrant_branch_path`.
Consider invocations of `flask.sansio.app.App.trap_http_exception` whose code
is in `src/flask/sansio/app.py`. An invocation means one Python `call` event
for exactly that function, counted 1-based in chronological order across the
entire test run. Re-entrant calls made while an earlier invocation is active
are separate invocations and take their positions in that same chronology.

For the 32nd invocation, report `executed_path`: the exact chronological
sequence of Python `line` events in that invocation's dynamic extent. The
dynamic extent begins immediately after its `call` event and ends at its
matching `return` event. Include line events from re-entrant invocations of
that exact function which occur before the selected frame returns. Exclude
all `call`, `return`, and `exception` events, and exclude every event from
other functions or files.

Preserve event order exactly; do not sort, group, deduplicate, or otherwise
normalize the sequence. Retain repeated and consecutive duplicate line events.
For every event, emit an object with exactly `file` (string), `func` (string),
and `line` (JSON integer). The `file` value is the repo-relative string
`src/flask/sansio/app.py`, and `func` is the fully qualified Python name
`flask.sansio.app.App.trap_http_exception` (for example, this naming format
would render a method as `package.module.Class.method`). Line numbers are
absolute, 1-based source line numbers in the named file as it exists in the
repository.

The function's `def` line is represented by the excluded `call` event, so it
does not appear in `executed_path`; there are no decorators on this function,
and docstring lines do not execute after the function has been defined. The
function has a multi-line condition: report each line number exactly when
Python emits its `line` event, including events on continuation-expression
lines, rather than collapsing the condition to one source line. In general,
for a multi-line statement or expression, use the line attached to the
runtime event (the statement's first line when that is the line Python
reports).

Return exactly the JSON object
`{"executed_path": [{"file": string, "func": string, "line": integer}, ...]}`.
The array is in the chronological order defined above with duplicates
retained. There are no additional keys and no stringification of line
numbers."""


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

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": selected_dynamic_extent(parse_events(args.trace_log))
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(oracle, indent=2, sort_keys=True) + "\n"
    args.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
