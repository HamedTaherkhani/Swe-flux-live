import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/serde.py"
TARGET_FUNC = "sqlglot.serde.dump"
EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\slocals=(?P<locals>\{.*\})$")

QUESTION = """Run every pytest test method in
`sqlglot_qa/serde_dump_m3_state/files/testcase.py::TestSerdeDumpProgramState`
against this repository and aggregate observations across all methods in that
class. Pytest collects these methods by their full pytest IDs in ascending
lexicographic order; execute them in that collection order. The answer covers
all invocations of `sqlglot.serde.dump`, defined in `sqlglot/serde.py`, that
occur during those methods, including recursive invocations made by `dump`
itself.

An invocation is one `call` of the exact target function, numbered 1-based in
chronological order, and ending at its matching `return`; nested recursive
invocations have independent frames. For every invocation, observe the target
function's own frame at every Python `line` event for which both frame-local
variables `i` and `payload` are already bound. A `line` event is delivered
immediately before Python executes the physical source line identified by the
event. Consequently, an event on an assignment line observes the variables'
values from before that assignment; in-place mutations made by an earlier line
are visible at the next event. In particular, executing `i += 1` first reads
and then writes `i`; the event on that augmented-assignment line observes the
pre-increment value, and a following line event observes the incremented value.

Only `line` events from the exact `sqlglot.serde.dump` frame count. Exclude
`call`, `return`, and `exception` events, all callee frames other than recursive
invocations of that exact function, and any comprehension or generator frame.
Include repeated events and events from every invocation. Line numbers are
absolute, 1-based physical lines in `sqlglot/serde.py` as it exists in the
repository, but line numbers are not included in the answer. For a multi-line
statement, use the physical line reported by Python without normalizing it to
the statement's first line. A decorator, `def`, or docstring line contributes
only if Python actually emits a `line` event there and both variables are
bound.

At each included event, form the two-element Python tuple `(i, payload)` from
the current integer and the current dictionary object, then take Python's
built-in `repr()` of that whole tuple. This is a snapshot at the event: use the
dictionary's current insertion order and contents, including mutations made in
place. Use ordinary Python representation recursively, including quotes around
strings and the spellings `None`, `True`, and `False` rather than JSON
spellings. Do not truncate, normalize, or reorder any part of the
representation. For example, a hypothetical observation whose integer is 2
and whose dictionary contains only a key `sample` mapped to null-like data
would be represented as `(2, {'sample': None})`. If either variable is not yet
bound, make no observation for that event; do not substitute an empty string
or JSON null.

Return one JSON object with exactly the key `unique_values`. Its value is a
list of the distinct tuple-representation strings observed across all included
events, invocations, and methods. Remove duplicates before sorting, and sort
the strings in ascending Python string order: lexicographic by Unicode code
point, with no secondary tie-breaker. Each list element is a JSON string whose
contents are the Python `repr()` described above; emit no invocation metadata,
line numbers, or additional keys."""


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
    if not all(isinstance(key, str) and isinstance(value, str)
               for key, value in locals_map.items()):
        fail("target locals payload does not map strings to repr strings")
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
            i_repr = frame_stack[-1].get("i")
            payload_repr = frame_stack[-1].get("payload")
            if i_repr is not None and payload_repr is not None:
                try:
                    i_value = ast.literal_eval(i_repr)
                except (SyntaxError, ValueError) as error:
                    fail(f"cannot parse i representation {i_repr!r}: {error}")
                if type(i_value) is not int or repr(i_value) != i_repr:
                    fail(f"i is not represented as a canonical integer: {i_repr!r}")
                if payload_repr.endswith("..."):
                    fail("payload representation was truncated")
                observed_values.add(f"({i_repr}, {payload_repr})")
        elif event == "return":
            frame_stack.pop()
        elif event == "exception":
            fail("target emitted an unexpected exception event")

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no invocation of {TARGET_FUNC}")
    if frame_stack:
        fail(f"trace ended with {len(frame_stack)} unfinished target invocation(s)")
    if not observed_values:
        fail("target trace contains no line observation with both i and payload bound")

    line_event_count = sum(line_counts.values())
    repeated_line_count = max(line_counts.values(), default=0)
    if line_event_count < 60:
        fail(f"target trace is too shallow: only {line_event_count} line events")
    if len(line_counts) < 8:
        fail(f"target trace is too narrow: only {len(line_counts)} distinct lines")
    if repeated_line_count < 5:
        fail(f"no target line executed at least five times (maximum {repeated_line_count})")
    if len(observed_values) < 8:
        fail(f"answer is too small: only {len(observed_values)} unique states")

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
        f"Wrote {output_path} with {len(observed_values)} unique states from "
        f"{invocation_count} invocations and {line_event_count} line events."
    )


if __name__ == "__main__":
    main()
