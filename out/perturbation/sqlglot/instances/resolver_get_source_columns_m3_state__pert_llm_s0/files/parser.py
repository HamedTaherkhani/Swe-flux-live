import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/resolver.py"
TARGET_FUNC = "sqlglot.optimizer.resolver.Resolver.get_source_columns"
EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\slocals=(?P<locals>\{.*\})$")

QUESTION = """Run every pytest test method in
`sqlglot_qa/resolver_get_source_columns_m3_state/files/testcase.py::TestResolverSourceColumnStates`
against this repository, and aggregate observations across all methods in that
class. Pytest collects the methods by their full pytest IDs in ascending
lexicographic order; execute them in that collection order. The answer covers
all invocations of
`sqlglot.optimizer.resolver.Resolver.get_source_columns`, defined in
`sqlglot/optimizer/resolver.py`, during those methods.

For each invocation, observe the target function's own frame at every Python
`line` event where its frame-local variable `columns` is already bound. A
`line` event is the event delivered immediately before Python executes the
source line identified by that event. An invocation is one `call` event for
the exact target function, numbered 1-based in chronological order; it ends
at its matching `return` event. Apply the rule independently to nested
invocations using their own frames. Include repeated line events and all
invocations, including cache-hit invocations, although a line event contributes
no observation when `columns` is not bound in that invocation.

Only events from the exact target frame count. Exclude its `call`, `return`,
and `exception` events, every callee frame, and comprehension or generator
frames such as a `<listcomp>` nested under the target. Line numbers themselves
are not part of the answer. For context, line numbers are absolute, 1-based
physical lines in the named file; for a multi-line statement Python may
attribute execution to a continued physical line, and no normalization to an
AST statement's starting line is performed. Decorator and `def` lines do not
create observations unless Python actually emits a `line` event for them.

At each included event, take Python's built-in `repr(columns)` of the whole
container as it exists immediately before that line executes. Use Python
spellings inside the string (`None`, `True`, and `False`, not JSON spellings),
and do not truncate or otherwise normalize the representation. For example,
a hypothetical two-element list containing a string and null-like value would
be represented as the string `['sample', None]`.

Return one JSON object with exactly the key `unique_values`. Its value is the
set of distinct observed representation strings: remove duplicates across all
events, invocations, and methods, then sort the strings in ascending Python
string order (lexicographic by Unicode code point, with no secondary
tie-breaker). The list elements are JSON strings containing those Python
`repr` values. Do not emit an empty string, JSON null, invocation metadata, or
any other key for an event without a bound `columns` variable."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if not match:
        fail(f"target event has no parseable locals mapping: {raw_line}")
    try:
        locals_map = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as error:
        fail(f"cannot parse target locals mapping: {error}")
    if not isinstance(locals_map, dict):
        fail("target locals payload is not a dictionary")
    return locals_map


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
    invocation_count = 0
    line_counts: dict[int, int] = {}
    frame_stack: list[dict[str, str]] = []
    observed_values: set[str] = set()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.search(raw_line)
        if not event_match:
            continue
        if event_match.group("func") != TARGET_FUNC:
            continue
        if not event_match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_event_count += 1
        event = event_match.group("event")

        if event == "call":
            invocation_count += 1
            frame_stack.append(parse_locals(raw_line))
            continue

        if not frame_stack:
            fail(f"target {event} event occurred outside an invocation")

        changed_locals = parse_locals(raw_line)
        frame_stack[-1].update(changed_locals)

        if event == "line":
            line = int(event_match.group("line"))
            line_counts[line] = line_counts.get(line, 0) + 1
            columns_repr = frame_stack[-1].get("columns")
            if columns_repr is not None:
                observed_values.add(columns_repr)
        elif event == "return":
            frame_stack.pop()

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no invocation of {TARGET_FUNC}")
    if frame_stack:
        fail(f"trace ended with {len(frame_stack)} unfinished target invocation(s)")
    if not observed_values:
        fail("target trace contains no line observation with bound columns")

    line_event_count = sum(line_counts.values())
    repeated_line_count = max(line_counts.values(), default=0)
    if line_event_count < 60:
        fail(f"target trace is too shallow: only {line_event_count} line events")
    if len(line_counts) < 8:
        fail(f"target trace is too narrow: only {len(line_counts)} distinct lines")
    if repeated_line_count < 5:
        fail(f"no target line executed at least five times (maximum {repeated_line_count})")
    if len(observed_values) < 8:
        fail(f"answer is too small: only {len(observed_values)} unique column states")

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(observed_values)},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} with {len(observed_values)} unique columns states "
        f"from {invocation_count} invocations and {line_event_count} line events."
    )


if __name__ == "__main__":
    main()
