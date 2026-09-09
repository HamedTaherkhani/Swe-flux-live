#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/_textwrap.py"
TARGET_FUNC = "click._textwrap._truncate_visible"
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r".*? locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test class
`click_qa/textwrap_truncate_visible_m3_state/files/testcase.py::TestTruncateVisibleState`
and aggregate over all twelve test methods in that class, identified by these
pytest ids (shown in their default ascending name order):
`TestTruncateVisibleState::test_alternating_color_runs`,
`TestTruncateVisibleState::test_dense_seeded_styles`,
`TestTruncateVisibleState::test_generated_plain_word`,
`TestTruncateVisibleState::test_initial_indent_budget`,
`TestTruncateVisibleState::test_interleaved_short_and_long_words`,
`TestTruncateVisibleState::test_narrow_visible_budget`,
`TestTruncateVisibleState::test_nested_sgr_sequences`,
`TestTruncateVisibleState::test_paragraph_preservation`,
`TestTruncateVisibleState::test_seeded_mixed_tokens`,
`TestTruncateVisibleState::test_subsequent_indent_budget`,
`TestTruncateVisibleState::test_tab_expansion_before_wrap`, and
`TestTruncateVisibleState::test_unicode_visible_characters`.

Consider every invocation caused by those methods of exactly
`click._textwrap._truncate_visible` in the repo-relative file
`src/click/_textwrap.py`. An invocation means one call of exactly that
function, counted 1-based in chronological execution order; every invocation
is included. Observe only executed line events in the target invocation's own
frame, never events in callers, callees, nested functions, or other frames. A
line event observes the frame locals immediately before the source statement
or expression on that line executes. Line numbers, where relevant to deciding
events, are absolute 1-based lines in the named file as it exists in the
repository. For a multi-line statement or expression, the event occurs on the
line where that executed statement or expression begins. The `def` line,
decorators, and docstring lines count only if Python actually produces a line
event there.

At each included line event where all three local variables `visible`, `i`,
and `cut` are already bound, form the state tuple `(visible, i, cut)` from
their values at that event. These are the target frame's current integer
values; an assignment changes a value only after its line executes, and an
augmented assignment such as `visible += 1` both reads and writes its variable,
so the line event on that augmented-assignment line observes the value before
the write. Represent each state as Python `repr()` of the whole tuple (for
example, `(-2, -4, -3)`), not as JSON and not by applying `str()` separately to
its elements.

Return exactly `{"unique_values": [str, ...]}` as JSON-compatible data.
Remove duplicate state-repr strings across all eligible line events and all
invocations, then sort the remaining strings in ascending lexicographic order
by Unicode code point. No secondary tie-breaker is needed after
deduplication. Each list element is always a Python-repr string; an absent
observation is omitted rather than represented by an empty string or JSON
null."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw: str, trace_line_number: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"could not parse locals on trace line {trace_line_number}: {error}")
    if not isinstance(value, dict):
        fail(f"locals payload on trace line {trace_line_number} is not a dict")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        fail(f"locals payload on trace line {trace_line_number} has invalid entries")
    return value


def parse_integer(raw: str, name: str, trace_line_number: int) -> int:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"could not parse {name!r} on trace line {trace_line_number}: {error}")
    if not isinstance(value, int) or isinstance(value, bool):
        fail(f"{name!r} is not an integer on trace line {trace_line_number}")
    return value


def collect_values(trace_text: str) -> tuple[set[str], int, int]:
    values: set[str] = set()
    current: dict[str, str] | None = None
    invocation_count = 0
    line_event_count = 0

    for trace_line_number, raw_line in enumerate(trace_text.splitlines(), 1):
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        event = match.group("event")
        changed = parse_locals(match.group("locals"), trace_line_number)
        if event == "call":
            if current is not None:
                fail("encountered a nested target invocation")
            invocation_count += 1
            current = dict(changed)
            continue

        if current is None:
            fail(f"encountered target {event} event outside an invocation")
        current.update(changed)

        if event == "line":
            line_event_count += 1
            names = ("visible", "i", "cut")
            if all(name in current for name in names):
                state = tuple(
                    parse_integer(current[name], name, trace_line_number) for name in names
                )
                values.add(repr(state))
        elif event == "return":
            current = None

    if current is not None:
        fail("trace ended before the final target invocation returned")
    return values, invocation_count, line_event_count


def main() -> None:
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

    values, invocation_count, line_event_count = collect_values(trace_text)
    if invocation_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if line_event_count == 0:
        fail(f"trace contains zero line events for {TARGET_FUNC}")
    if not values:
        fail("no line event observed all of 'visible', 'i', and 'cut'")

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(values)},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
