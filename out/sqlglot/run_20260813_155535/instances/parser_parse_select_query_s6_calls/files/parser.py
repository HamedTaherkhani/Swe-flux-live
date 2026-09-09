import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/parser.py"
TARGET_FUNC = "sqlglot.parser.Parser._parse_select_query"
TRACKED_FUNCS = (
    TARGET_FUNC,
    "sqlglot.parser.Parser._parse_with",
    "sqlglot.parser.Parser._parse_statement",
    "sqlglot.parser.Parser._parse_select",
    "sqlglot.parser.Parser._parse_projections",
    "sqlglot.parser.Parser._parse_from",
    "sqlglot.parser.Parser._parse_query_modifiers",
    "sqlglot.parser.Parser._parse_set_operations",
    "sqlglot.parser.Parser._parse_limit",
    "sqlglot.parser.Parser._parse_subquery",
    "sqlglot.parser.Parser._parse_derived_table_values",
    "sqlglot.parser.Parser.expression",
    "sqlglot.parser.Parser._parse_value",
    "sqlglot.parser.Parser._parse_hint",
    "sqlglot.parser.Parser._parse_into",
    "sqlglot.parser.Parser._parse_wrapped_select",
)
TRACKED_FUNC_SET = set(TRACKED_FUNCS)

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`sqlglot_qa/parser_parse_select_query_s6_calls/files/testcase.py::TestParseSelectQueryCalls::test_generated_ctes_and_set_operations`
against this repository. During the first invocation of
`sqlglot.parser.Parser._parse_select_query` in `sqlglot/parser.py`, what is the
exact chronological order of calls to the following tracked functions?

- `sqlglot.parser.Parser._parse_select_query`
- `sqlglot.parser.Parser._parse_with`
- `sqlglot.parser.Parser._parse_statement`
- `sqlglot.parser.Parser._parse_select`
- `sqlglot.parser.Parser._parse_projections`
- `sqlglot.parser.Parser._parse_from`
- `sqlglot.parser.Parser._parse_query_modifiers`
- `sqlglot.parser.Parser._parse_set_operations`
- `sqlglot.parser.Parser._parse_limit`
- `sqlglot.parser.Parser._parse_subquery`
- `sqlglot.parser.Parser._parse_derived_table_values`
- `sqlglot.parser.Parser.expression`
- `sqlglot.parser.Parser._parse_value`
- `sqlglot.parser.Parser._parse_hint`
- `sqlglot.parser.Parser._parse_into`
- `sqlglot.parser.Parser._parse_wrapped_select`

An invocation is one Python `call` trace event for the exact function and
invocations are numbered 1-based in chronological execution order. A `call`
event occurs when the Python function frame is entered, before its first
executable `line` event. The requested interval begins with the `call` event
that starts the first target invocation and ends with its matching `return`
event. Nested invocations of the target do not end that interval.

Include the interval-opening call to the target itself and every `call` event
for an exact function in the tracked set whenever the first target invocation
is on the call stack. This is a transitive rule: the tracked function need not
be called directly by the target's own frame. Exclude calls before or after
that interval, calls to every function not listed above, builtins, and
comprehension or generator frames whose exact dotted identity is not listed.
Retain repeated calls. If a tracked generator function is resumed and Python
emits another `call` event for that resumption, retain that event as another
entry.

Return one JSON object with exactly the key `function_call_order`. Its value
must be a list of objects, each with exactly two string keys: `file` and
`func`. For every entry, `file` is the repo-relative POSIX path
`sqlglot/parser.py`; `func` is the fully dotted identity in
`module.Class.method` or `module.function` format. For example, method `run`
on class `Worker` in module `pkg.jobs` is `pkg.jobs.Worker.run`.

Preserve the chronological order in which the executing thread delivers the
events; event-delivery order is the total-order tie-breaker if clock times
would be equal. Do not sort or deduplicate entries. There are no line numbers
or formatted runtime values in the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    target_invocation_count = 0
    target_depth = 0
    active = False
    completed = False
    target_line_count = 0
    call_order = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue

        traced_file = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if not traced_file.endswith(TARGET_FILE):
            continue

        if func == TARGET_FUNC:
            target_event_count += 1

        if event == "call" and func == TARGET_FUNC:
            if not active and not completed:
                target_invocation_count += 1
                if target_invocation_count == 1:
                    active = True
                    target_depth = 1
            elif active:
                target_depth += 1

        if active and event == "call" and func in TRACKED_FUNC_SET:
            call_order.append({"file": TARGET_FILE, "func": func})

        if active and func == TARGET_FUNC and event == "line":
            target_line_count += 1

        if active and event == "return" and func == TARGET_FUNC:
            target_depth -= 1
            if target_depth == 0:
                active = False
                completed = True

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_invocation_count == 0:
        fail(f"trace contains no invocation of {TARGET_FUNC}")
    if not completed:
        fail(f"first invocation of {TARGET_FUNC} has no matching return event")
    if not call_order:
        fail("first target invocation contains no tracked call events")
    if len(call_order) < 10 or len({entry["func"] for entry in call_order}) < 2:
        fail(
            "tracked call order is too shallow: "
            f"{len(call_order)} calls across "
            f"{len({entry['func'] for entry in call_order})} functions"
        )
    if target_line_count < 40:
        fail(
            "first target invocation is too shallow: "
            f"{target_line_count} target line events"
        )

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} with {len(call_order)} calls to "
        f"{len({entry['func'] for entry in call_order})} tracked functions."
    )


if __name__ == "__main__":
    main()
