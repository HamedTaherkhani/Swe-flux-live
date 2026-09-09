from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET = "click.shell_completion._resolve_incomplete"
TRACKED = {
    "click.shell_completion._is_incomplete_argument",
    "click.shell_completion._is_incomplete_option",
    "click.shell_completion._start_of_option",
}
INVOCATION = 11

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test
`click_qa/shell_completion_resolve_incomplete_s6_calls/files/testcase.py::ShellCompletionResolveIncompleteCallsTest::test_scripted_completion_workload`.
During that test, consider the 11th invocation of
`click.shell_completion._resolve_incomplete` in
`src/click/shell_completion.py`. An invocation is one entry into that
function's Python frame, numbered from 1 in the chronological order in which
the entries occur during this test method.

What is the exact chronological sequence of calls to this tracked set of
functions while that 11th target invocation is on the call stack:
`click.shell_completion._is_incomplete_argument`,
`click.shell_completion._is_incomplete_option`, and
`click.shell_completion._start_of_option`?

Count a call whenever Python begins executing a frame for one of those three
listed functions after the target frame has been entered and before that
target frame returns. Include matching calls at every nesting level, both
calls made directly by the target and matching transitive calls made beneath
it. Do not include the entry call of `_resolve_incomplete` itself, calls to
any function outside the three-function tracked set, builtins, or
comprehension frames. Retain every repeated call; do not deduplicate. If a
listed function were a generator, each resumption that begins with a Python
`call` event would count as another call.

Return JSON with exactly one key, `function_call_order`, whose value is a list
of objects with exactly the keys `file` and `func`, both strings. Each `file`
is the POSIX repo-relative path of the file containing the called function.
Each `func` is the full dotted Python identity
`module.Class.method` or `module.function`; for example,
`click.core.Command.main`. Preserve the runtime event-stream order exactly;
it is already a total chronological order, so perform no sorting and use no
secondary tie-breaker. Repeated objects remain repeated. The surrounding
JSON uses normal JSON string serialization."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)

    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, str, str]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)

        if match is not None:
            events.append(
                (match.group("file"), match.group("func"), match.group("event"))
            )

    target_events = [event for event in events if event[1] == TARGET]

    if not target_events:
        fail(f"trace contains zero events for target function {TARGET}")

    repo_root = Path.cwd().resolve()
    target_invocations = 0
    active = False
    completed = False
    call_order: list[dict[str, str]] = []
    seen_tracked: set[str] = set()

    for filename, func, event in events:
        if func == TARGET and event == "call":
            target_invocations += 1

            if target_invocations == INVOCATION:
                active = True

            continue

        if active and func in TRACKED and event == "call":
            absolute_file = Path(filename).resolve()

            try:
                relative_file = absolute_file.relative_to(repo_root).as_posix()
            except ValueError:
                fail(f"tracked file is outside repository: {absolute_file}")

            call_order.append({"file": relative_file, "func": func})
            seen_tracked.add(func)

        if active and func == TARGET and event == "return":
            active = False
            completed = True
            break

    if target_invocations < INVOCATION:
        fail(
            f"trace has only {target_invocations} target invocations; "
            f"invocation {INVOCATION} is required"
        )

    if not completed:
        fail(f"target invocation {INVOCATION} has no return event")

    if not call_order:
        fail(f"target invocation {INVOCATION} contains no tracked calls")

    missing = sorted(TRACKED - seen_tracked)

    if missing:
        fail(f"target invocation {INVOCATION} did not call tracked functions: {missing}")

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
