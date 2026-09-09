from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/utils.py"
TARGET_FUNC = "click.utils._make_default_short_help"
FOR_OBSERVATION_LINE = 87
WHILE_OBSERVATION_LINE = 105
EMPTY_OBSERVATION_LINE = 77

FOR_PREDICATES = (
    '(word[-1] == ".") == ((i + max_length) % 5 == 0)',
    "len(word) <= max_length // 3",
    "total_length <= max_length // 2",
    "word.isascii()",
)
WHILE_PREDICATE = "total_length != max_length * 2"
EMPTY_PREDICATE = "max_length > len(help)"
ALL_PREDICATES = tuple(
    sorted(FOR_PREDICATES + (WHILE_PREDICATE, EMPTY_PREDICATE))
)

QUESTION = """Run every pytest test method in the class `TestGeneratedShortHelp` in `click_qa/utils_make_default_short_help_m7_invariants/files/testcase.py`, equivalently every collected pytest id below `click_qa/utils_make_default_short_help_m7_invariants/files/testcase.py::TestGeneratedShortHelp`. All 12 collected test methods contribute, and the answer aggregates observations across ALL of them. Use pytest's normal collection order, which for this `unittest.TestCase` is ascending test-method name and therefore ascending full pytest id. During that complete run, consider every invocation of the target function `click.utils._make_default_short_help` in the repository file `src/click/utils.py`.

Evaluate these six candidate predicates verbatim at their assigned observation points:

- `(word[-1] == ".") == ((i + max_length) % 5 == 0)`
- `total_length != max_length * 2`
- `len(word) <= max_length // 3`
- `max_length > len(help)`
- `total_length <= max_length // 2`
- `word.isascii()`

At every CPython `sys.settrace` line event in the target frame whose `f_lineno` is 87, evaluate `(word[-1] == ".") == ((i + max_length) % 5 == 0)`, `len(word) <= max_length // 3`, `total_length <= max_length // 2`, and `word.isascii()` using the local values present immediately before the augmented assignment `total_length += len(word) + (i > 0)` executes. At that point the current `enumerate(words)` iteration has assigned `i` and `word`, but line 87 has not yet changed `total_length`. Each qualifying event contributes one independent observation to each of these four predicates.

At every line event in the same target frame whose `f_lineno` is 105, evaluate only `total_length != max_length * 2`, using the locals immediately before the augmented subtraction on that line executes. Each execution of line 105 is one while-loop iteration for this question, including its current pre-subtraction values of `max_length` and `total_length`; each such event contributes one observation. At every line event in the same target frame whose `f_lineno` is 77, evaluate only `max_length > len(help)`, using the locals immediately before the `return ""` statement executes. If that branch is never reached, this predicate receives no substitute observations. Do not evaluate any predicate at any other source line.

Here a “line event” means exactly an event for which a trace function installed with Python's standard `sys.settrace` API receives `event == "line"`; use `f_lineno` from that event's frame. Line numbers are absolute, 1-based physical lines in `src/click/utils.py` as checked out. Reaching an observation line means reaching it before executing the statement that begins there; for a multi-line statement or expression, use the physical line where it begins. The `def` line, decorator lines, comments, and docstring lines are not observation points.

Use ordinary Python semantics on the actual local objects. String indexing, equality, integer floor division, modulo, addition, `len`, and `str.isascii()` have their standard meanings; `is` is not used. The augmented assignments on lines 87 and 105 both read and then write `total_length`, but these observation points explicitly use the pre-write value. Evaluate Python expressions directly; do not serialize local values or apply `repr()` or `str()` before evaluation.

An invocation is one Python `call` of `click.utils._make_default_short_help` during the complete class run, numbered from 1 in chronological call order if needed while computing; invocation numbers do not appear in the answer. Count every qualifying event across every invocation and test method. Do not deduplicate repeated local states, predicate results, or events.

For each predicate, `observations` is its total number of evaluations, and `violations` is the number whose Python boolean result is false. Set `held_always` to the JSON boolean result of `violations == 0` only when `observations` is positive. A predicate with zero observations is not evaluable and must be reported with `observations: 0`, `violations: 0`, and `held_always: false`.

Return exactly `{"invariant_report": [{"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}]}`. The `invariant_report` value is a JSON array containing exactly one object per candidate predicate. `predicate` is the verbatim expression above encoded directly as a JSON string, not Python `repr()`; counts are JSON integers, and `held_always` is a JSON boolean. Sort entries ascending by `predicate` using Python string ordering. The predicate strings are unique, so no tie occurs; if a tie hypothetically occurred, preserve the candidate-list order above as the final tie-breaker. Do not omit or deduplicate entries, and do not use JSON null, an empty string, or an absent field for any answer value."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def local_value(current: dict[str, str], name: str, line: int):
    if name not in current:
        fail(f"local {name!r} is unavailable at observation line {line}")
    try:
        return ast.literal_eval(current[name])
    except (SyntaxError, ValueError) as error:
        fail(f"cannot decode local {name!r} at line {line}: {error}")


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        + re.escape(TARGET_FUNC)
        + r" event=(?P<event>call|line|return|exception)"
        + r"(?:.*?) locals=(?P<locals>\{.*\})$"
    )
    counts = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in ALL_PREDICATES
    }
    current: dict[str, str] | None = None
    target_events = 0
    calls = 0
    returns = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as error:
            fail(f"cannot parse locals from target trace event: {error}")
        if not isinstance(changed, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed.items()
        ):
            fail("target trace event has malformed locals")

        if event == "call":
            if current is not None:
                fail("overlapping target invocations are not supported")
            current = {}
            calls += 1
        if current is None:
            fail(f"target {event} event at line {line} occurred outside an invocation")
        current.update(changed)

        if event == "line" and line == FOR_OBSERVATION_LINE:
            i = local_value(current, "i", line)
            max_length = local_value(current, "max_length", line)
            total_length = local_value(current, "total_length", line)
            word = local_value(current, "word", line)
            if not (
                isinstance(i, int)
                and isinstance(max_length, int)
                and isinstance(total_length, int)
                and isinstance(word, str)
            ):
                fail("for-loop observation locals have unexpected types")
            results = {
                '(word[-1] == ".") == ((i + max_length) % 5 == 0)': (
                    (word[-1] == ".") == ((i + max_length) % 5 == 0)
                ),
                "len(word) <= max_length // 3": len(word) <= max_length // 3,
                "total_length <= max_length // 2": (
                    total_length <= max_length // 2
                ),
                "word.isascii()": word.isascii(),
            }
            for predicate, held in results.items():
                counts[predicate]["observations"] += 1
                counts[predicate]["violations"] += int(not held)

        if event == "line" and line == WHILE_OBSERVATION_LINE:
            max_length = local_value(current, "max_length", line)
            total_length = local_value(current, "total_length", line)
            if not isinstance(max_length, int) or not isinstance(total_length, int):
                fail("while-loop observation locals have unexpected types")
            held = total_length != max_length * 2
            counts[WHILE_PREDICATE]["observations"] += 1
            counts[WHILE_PREDICATE]["violations"] += int(not held)

        if event == "line" and line == EMPTY_OBSERVATION_LINE:
            max_length = local_value(current, "max_length", line)
            help_text = local_value(current, "help", line)
            if not isinstance(max_length, int) or not isinstance(help_text, str):
                fail("empty-help observation locals have unexpected types")
            held = max_length > len(help_text)
            counts[EMPTY_PREDICATE]["observations"] += 1
            counts[EMPTY_PREDICATE]["violations"] += int(not held)

        if event == "return":
            returns += 1
            current = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if calls != returns:
        fail(f"target call/return mismatch: {calls} calls, {returns} returns")
    if current is not None:
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
