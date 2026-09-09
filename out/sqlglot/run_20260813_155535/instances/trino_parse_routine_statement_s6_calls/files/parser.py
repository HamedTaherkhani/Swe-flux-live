import argparse
import json
import re
from pathlib import Path


TARGET = "sqlglot.parsers.trino.TrinoParser._parse_routine_statement"
TRACKED = {
    "sqlglot.parsers.trino.TrinoParser._parse_routine_statement",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_statements",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_block",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_if",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_case",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_while",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_loop",
    "sqlglot.parsers.trino.TrinoParser._parse_routine_repeat",
}
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`sqlglot_qa/trino_parse_routine_statement_s6_calls/files/testcase.py::TestTrinoRoutineCallFlow::test_generated_routine_tree`.
During that test, consider invocation 1 of
`sqlglot.parsers.trino.TrinoParser._parse_routine_statement` in
`sqlglot/parsers/trino.py`. An invocation means one Python `call` event for
that function; invocations are numbered from 1 in chronological interpreter
event order.

Report `function_call_order`, the exact chronological sequence of Python
`call` events beginning with that invocation's own entry event and ending
immediately before its matching `return` event. Include every event for any of
the following functions whenever invocation 1 of the target remains on the
call stack, including nested and transitive calls:

* `sqlglot.parsers.trino.TrinoParser._parse_routine_statement`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_statements`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_block`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_if`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_case`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_while`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_loop`
* `sqlglot.parsers.trino.TrinoParser._parse_routine_repeat`

Ignore calls to every function outside this exact set, even when such a call
is made directly by a tracked frame. Preserve repeated calls; do not
deduplicate or sort. Ordering is the interpreter's total event order (the test
runs in one thread, so ties do not occur). A generator resumption would count
as another call event and would appear in its event position, but no event
other than `call` is an output element.

Return exactly
`{"function_call_order": [{"file": <str>, "func": <str>}, ...]}`.
For each event, `file` is the repository-relative POSIX path obtained from the
executing code object's filename, and `func` is the full dotted
`module.Class.method` qualname; for example, a hypothetical method could be
`package.module.Widget.run`. Keep both values as ordinary JSON strings. The
first event is included, the matching return is not, and no calls after that
return are included."""


def parse_events(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        raise SystemExit(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    events = []
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue

        event = match.group("event")
        func = match.group("func")
        if func == TARGET:
            target_events += 1
        if func not in TRACKED:
            continue

        absolute_file = Path(match.group("file"))
        try:
            relative_file = absolute_file.relative_to("/testbed").as_posix()
        except ValueError as error:
            raise SystemExit(f"traced file is outside /testbed: {absolute_file}") from error

        events.append({"event": event, "file": relative_file, "func": func})

    if target_events == 0:
        raise SystemExit(f"trace contains zero events for target function {TARGET}")
    return events


def call_order(events: list[dict[str, str]]) -> list[dict[str, str]]:
    active = False
    stack: list[str] = []
    order: list[dict[str, str]] = []

    for event in events:
        kind = event["event"]
        func = event["func"]

        if not active:
            if kind == "call" and func == TARGET:
                active = True
                stack.append(func)
                order.append({"file": event["file"], "func": func})
            continue

        if kind == "call":
            stack.append(func)
            order.append({"file": event["file"], "func": func})
        elif kind == "return":
            if not stack or stack[-1] != func:
                raise SystemExit(
                    f"unbalanced tracked return for {func}; stack is {stack!r}"
                )
            stack.pop()
            if not stack:
                break

    if not active:
        raise SystemExit("target invocation 1 has no call event")
    if stack:
        raise SystemExit(f"target invocation 1 has no matching return; stack is {stack!r}")
    if not order:
        raise SystemExit("computed call order is empty")

    seen = {item["func"] for item in order}
    missing = sorted(TRACKED - seen)
    if missing:
        raise SystemExit(f"trace did not capture calls for tracked functions: {missing}")
    return order


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order(parse_events(args.trace_log))},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2))


if __name__ == "__main__":
    main()
