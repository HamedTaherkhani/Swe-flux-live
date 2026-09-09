from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/formatting.py"
TARGET_FUNC = "click.formatting.wrap_text"
PARAGRAPH_OBSERVATION_LINE = 101
RAW_PARAGRAPH_OBSERVATION_LINE = 103
SINGLE_PARAGRAPH_OBSERVATION_LINE = 72

PARAGRAPH_PREDICATES = (
    "indent == 0",
    "len(text.split()) > 0",
    "len(text.splitlines()) == 1",
    "raw is False",
)
RAW_PARAGRAPH_PREDICATE = "len(text.split()) < 53"
SINGLE_PARAGRAPH_PREDICATE = "text == text.expandtabs()"
ALL_PREDICATES = tuple(
    sorted(
        PARAGRAPH_PREDICATES
        + (RAW_PARAGRAPH_PREDICATE, SINGLE_PARAGRAPH_PREDICATE)
    )
)

QUESTION = """Run every pytest test method in the class `TestGeneratedHelpLayouts` in `click_qa/formatting_wrap_text_m7_invariants/files/testcase.py`, equivalently every collected pytest id below `click_qa/formatting_wrap_text_m7_invariants/files/testcase.py::TestGeneratedHelpLayouts`. All 12 collected test methods contribute. Use pytest's normal collection order, which for this class is ascending test-method name and therefore ascending full pytest id. Aggregate observations across ALL test methods in that class. During that complete run, consider every invocation of the target function `click.formatting.wrap_text` in the repository file `src/click/formatting.py`.

Evaluate the following six candidate predicates verbatim, at the observation point assigned below:

- `indent == 0`
- `len(text.split()) < 53`
- `len(text.split()) > 0`
- `len(text.splitlines()) == 1`
- `raw is False`
- `text == text.expandtabs()`

For each CPython `sys.settrace` line event in the `wrap_text` frame whose `f_lineno` is 101, evaluate `indent == 0`, `len(text.split()) > 0`, `len(text.splitlines()) == 1`, and `raw is False`. This definition deliberately counts every line event CPython emits for that `with` statement, including an event emitted when control returns to the `with` line as its context manager completes; do not collapse multiple events for the same paragraph. The tuple-target assignment at line 100 has completed before any such event, so `indent`, `raw`, and `text` are the current paragraph tuple's local values. Each qualifying event contributes one observation independently to each of these four predicates.

For each CPython `sys.settrace` line event in the same frame whose `f_lineno` is 103, evaluate only `len(text.split()) < 53`, using the local values present immediately before the `rv.append(wrapper.indent_only(text))` statement executes. For each such line event whose `f_lineno` is 72, evaluate only `text == text.expandtabs()`, using the local values immediately before the `return wrapper.fill(text)` statement executes; at that point line 64's assignment has already replaced `text` with the result of `text.expandtabs()`. Each qualifying event contributes one observation to its assigned predicate. Do not evaluate any predicate at any other source line, and do not substitute observations from another branch when an assigned observation point is not reached. Here a “line event” means exactly an event for which a trace function installed with Python's standard `sys.settrace` API receives `event == "line"`; `f_lineno` is read from that event's frame.

Use ordinary Python semantics on the actual local objects at each point. In particular, `is` is object identity; `str.split()` and `str.splitlines()` are called without arguments; `len()` returns their ordinary integer lengths; and `str.expandtabs()` uses its default tab size. Each predicate evaluation produces one boolean. A violation is an evaluation whose result is false. For each predicate, `observations` is its total number of evaluations across all target invocations in all test methods, `violations` is the number of those evaluations that are false, and `held_always` is exactly `violations == 0` when at least one observation exists. A predicate with no observations is not evaluable and must instead be reported as `observations: 0`, `violations: 0`, and `held_always: false`.

An invocation means one Python call of `click.formatting.wrap_text` during the complete class run. If invocations need to be distinguished while computing the totals, number them from 1 in chronological call order; invocation numbers do not appear in the answer. Counts include duplicate outcomes and repeated executions: there is no deduplication of observations.

Line numbers are absolute, 1-based physical lines in `src/click/formatting.py` as checked out. An execution of an observation line means the runtime reaches that source line before executing the statement that begins there. For a multi-line statement, use the physical line on which that statement or expression begins. The `def` line, decorator lines, and docstring lines are not observation points here.

Return exactly `{"invariant_report": [{"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}]}`. The `invariant_report` value is a JSON array with exactly one object per candidate predicate. `predicate` is the verbatim expression above as a direct JSON string, not Python `repr()`; counts are JSON integers and `held_always` is a JSON boolean. Sort entries ascending by `predicate` using Python string ordering. Predicate strings are unique, so no tie can occur; if a tie hypothetically occurred, preserve the order in the candidate list above as the final tie-breaker. Do not omit or deduplicate entries, and do not use JSON null, an empty string, or an absent field for any value."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_local_value(current_locals: dict[str, str], name: str, line: int):
    if name not in current_locals:
        fail(f"local {name!r} is unavailable at observation line {line}")
    try:
        return ast.literal_eval(current_locals[name])
    except (SyntaxError, ValueError) as error:
        fail(f"cannot decode local {name!r} at line {line}: {error}")


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        + re.escape(TARGET_FUNC)
        + r" event=(?P<event>call|line|return|exception)"
        + r"(?:.*?) locals=(?P<locals>\{.*\})$"
    )
    counts = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in ALL_PREDICATES
    }
    current_locals: dict[str, str] | None = None
    target_events = 0
    target_calls = 0
    target_returns = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as error:
            fail(f"cannot parse locals from target trace event: {error}")
        if not isinstance(changed_locals, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed_locals.items()
        ):
            fail("target trace event has malformed locals")

        if event == "call":
            if current_locals is not None:
                fail("overlapping target invocations are not supported")
            current_locals = {}
            target_calls += 1
        if current_locals is None:
            fail(f"target {event} event at line {line} occurred outside an invocation")
        current_locals.update(changed_locals)

        if event == "line" and line == PARAGRAPH_OBSERVATION_LINE:
            indent = parse_local_value(current_locals, "indent", line)
            raw = parse_local_value(current_locals, "raw", line)
            text = parse_local_value(current_locals, "text", line)
            if not isinstance(indent, int) or not isinstance(raw, bool) or not isinstance(
                text, str
            ):
                fail("paragraph observation locals have unexpected types")
            results = {
                "indent == 0": indent == 0,
                "len(text.split()) > 0": len(text.split()) > 0,
                "len(text.splitlines()) == 1": len(text.splitlines()) == 1,
                "raw is False": raw is False,
            }
            for predicate, held in results.items():
                counts[predicate]["observations"] += 1
                counts[predicate]["violations"] += int(not held)

        if event == "line" and line == RAW_PARAGRAPH_OBSERVATION_LINE:
            text = parse_local_value(current_locals, "text", line)
            if not isinstance(text, str):
                fail("raw-paragraph observation local text is not a string")
            held = len(text.split()) < 53
            counts[RAW_PARAGRAPH_PREDICATE]["observations"] += 1
            counts[RAW_PARAGRAPH_PREDICATE]["violations"] += int(not held)

        if event == "line" and line == SINGLE_PARAGRAPH_OBSERVATION_LINE:
            text = parse_local_value(current_locals, "text", line)
            if not isinstance(text, str):
                fail("single-paragraph observation local text is not a string")
            held = text == text.expandtabs()
            counts[SINGLE_PARAGRAPH_PREDICATE]["observations"] += 1
            counts[SINGLE_PARAGRAPH_PREDICATE]["violations"] += int(not held)

        if event == "return":
            target_returns += 1
            current_locals = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if target_calls != target_returns:
        fail(
            f"target call/return mismatch: {target_calls} calls, "
            f"{target_returns} returns"
        )
    if current_locals is not None:
        fail("trace ended during an active target invocation")
    if sum(item["observations"] for item in counts.values()) == 0:
        fail("trace contains no predicate observations")

    report = []
    for predicate in ALL_PREDICATES:
        observations = counts[predicate]["observations"]
        violations = counts[predicate]["violations"]
        report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": report}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {
                    "held_always": "bool",
                    "observations": "int",
                    "predicate": "str",
                    "violations": "int",
                }
            ]
        },
        "oracle_answer": parse_trace(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
