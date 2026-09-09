#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/sessions.py"
TARGET_FUNC = "flask.sessions.SecureCookieSessionInterface.open_session"
TRACKED_FUNCTIONS = (
    "flask.sessions.SecureCookieSession.__init__",
    "flask.sessions.SecureCookieSessionInterface.get_signing_serializer",
    "flask.sessions.SecureCookieSessionInterface.open_session",
    "flask.sessions.SessionInterface.get_cookie_name",
    "flask.sessions.SessionInterface.make_null_session",
    "flask.sessions._lazy_sha1",
)
EVENT_RE = re.compile(
    r"(?P<path>/\S*src/flask/sessions\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`flask_qa/sessions_open_session_m6_calls/files/testcase.py::TestOpenSessionCallGraph::test_seeded_cookie_matrix`
from the repository root. The primary target is
`SecureCookieSessionInterface.open_session` (runtime qualified name
`flask.sessions.SecureCookieSessionInterface.open_session`) in
`src/flask/sessions.py`.

Determine which members of this exact tracked function set execute at least
once during the named test:

- `{"file": "src/flask/sessions.py", "func": "flask.sessions.SecureCookieSession.__init__"}`
- `{"file": "src/flask/sessions.py", "func": "flask.sessions.SecureCookieSessionInterface.get_signing_serializer"}`
- `{"file": "src/flask/sessions.py", "func": "flask.sessions.SecureCookieSessionInterface.open_session"}`
- `{"file": "src/flask/sessions.py", "func": "flask.sessions.SessionInterface.get_cookie_name"}`
- `{"file": "src/flask/sessions.py", "func": "flask.sessions.SessionInterface.make_null_session"}`
- `{"file": "src/flask/sessions.py", "func": "flask.sessions._lazy_sha1"}`

A tracked function is covered if Python enters the exact listed function body
in the named file at least once while executing the test. Count an entry
regardless of which frame called it: calls made directly by the test, direct
calls from `open_session`, and transitive calls while another listed function
is on the stack are treated identically. Calls to unlisted functions,
builtins, inherited or overridden implementations with a different runtime
qualified name, and same-named functions in other files are excluded. A
runtime function identity is the dotted `module.Class.method` or
`module.function` qualified name; for example, a method could be
`package.widgets.Widget.render`.

Coverage is a set, not a call count or sequence. Repeated calls and recursive
entries do not add duplicate objects. If a listed generator were resumed,
each runtime re-entry would qualify as an entry, but it would still contribute
only one object. First filter to runtime function-entry events for the exact
tracked set, then remove duplicates by exact equality of both `file` and
`func`. Sort the remaining objects in ascending lexicographic order by the
two-element tuple `(file, func)`, comparing Unicode code points with `file` as
the primary key and `func` as the tie-breaker.

Return exactly one JSON object with key `covered_functions`. Its value is a
JSON array of objects, each having exactly two string keys: `file` and `func`.
Use the repo-relative POSIX path shown in the tracked set for `file`, and the
fully qualified runtime name shown there for `func`. No line numbers, call
counts, return values, exception names, `repr`/`str` formatting, or null/empty
sentinel values are part of the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_trace(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    covered = set()
    line_events = 0
    distinct_lines = set()
    call_events = 0
    called_functions = set()

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None:
                continue

            func = match.group("func")
            event = match.group("event")
            if func == TARGET_FUNC:
                target_events += 1
            if func not in TRACKED_FUNCTIONS:
                continue

            if event == "line":
                line_events += 1
                distinct_lines.add((func, int(match.group("line"))))
            elif event == "call":
                call_events += 1
                called_functions.add(func)
                covered.add((TARGET_FILE, func))

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if line_events < 50:
        fail(f"expected at least 50 tracked line events, found {line_events}")
    if len(distinct_lines) < 8:
        fail(
            "expected at least 8 distinct tracked executed lines, "
            f"found {len(distinct_lines)}"
        )
    if call_events < 15:
        fail(f"expected at least 15 tracked call events, found {call_events}")
    if len(called_functions) < 4:
        fail(
            "expected at least 4 distinct called tracked functions, "
            f"found {len(called_functions)}"
        )
    if len(covered) == len(TRACKED_FUNCTIONS):
        fail("expected at least one tracked function not to be covered")

    return [
        {"file": file_name, "func": func_name}
        for file_name, func_name in sorted(covered)
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"covered_functions": parse_trace(args.trace_log)},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
