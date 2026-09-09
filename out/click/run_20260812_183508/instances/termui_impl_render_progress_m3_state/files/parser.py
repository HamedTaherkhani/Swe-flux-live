#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "click._termui_impl.ProgressBar.render_progress"
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r".*? locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test class
`click_qa/termui_impl_render_progress_m3_state/files/testcase.py::TestRenderProgressState`.
Aggregate the run over all twelve collected test methods in that class:
`test_fixed_width_positions`, `test_seeded_percentages`,
`test_unknown_length_generator`, `test_manual_variable_updates`,
`test_batched_updates`, `test_generated_item_labels`,
`test_hidden_progress`, `test_non_tty_progress`,
`test_autowidth_rotating_terminal`, `test_autowidth_shrinking_terminal`,
`test_empty_iterable_edge`, and `test_unicode_custom_template`. Consider every
invocation of `click._termui_impl.ProgressBar.render_progress` in
`src/click/_termui_impl.py` caused by those methods.

What is the sorted set of distinct values taken by the local variable `buf` at
all executed line events in those invocations for which `buf` is already
bound? Observe the target invocation's own frame only; events in callers,
callees, nested functions, and other frames do not count. A line event observes
the frame's locals immediately before the source statement or expression at
that line executes. For a multi-line statement or expression, its event is on
the absolute 1-based line in `src/click/_termui_impl.py` where that executed
statement or expression begins. The function `def` line, decorators, and
docstring lines contribute only if Python executes a line event there and
`buf` is already bound. An invocation means one call of exactly the named
function during this class run, counted 1-based in chronological execution
order; all invocations are included.

Represent each observed value as Python `repr(buf)` of the whole list, so
strings inside it use Python spellings and quoting (for example,
`['sample', 2]`, not a JSON rendering of that list). Remove duplicate repr
strings across all line events and all invocations. Sort the remaining strings
in ascending lexicographic order by Unicode code point, with no secondary
tie-breaker needed because duplicates have been removed. The empty list, if
observed, is represented by the two-character string `[]`; no observation is
ever represented by JSON null or by an omitted list element.

Return exactly `{"unique_values": [str, ...]}` as JSON-compatible data, where
every list element follows the Python-repr rule above."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw: str, line_number: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"could not parse locals on trace line {line_number}: {error}")
    if not isinstance(value, dict):
        fail(f"locals payload on trace line {line_number} is not a dict")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        fail(f"locals payload on trace line {line_number} has invalid entries")
    return value


def collect_values(trace_text: str) -> tuple[set[str], int, int]:
    values: set[str] = set()
    current: dict[str, str] | None = None
    invocation_count = 0
    line_event_count = 0

    for trace_line_number, raw_line in enumerate(trace_text.splitlines(), 1):
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
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
            if "buf" in current:
                values.add(current["buf"])
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
        fail("no line event observed a bound local variable 'buf'")

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
