#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.templating.DispatchingJinjaLoader.list_templates"
OBSERVATION_LINE = 118

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/flask/templating\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r".* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test
`flask_qa/templating_list_templates_m7_invariants/files/testcase.py::TestDispatchingLoaderInvariants::test_seeded_template_inventory`
against this repository. Across every invocation of
`flask.templating.DispatchingJinjaLoader.list_templates` in
`src/flask/templating.py`, did the candidate predicate
`(sum((position + 1) * ord(character) for position, character in enumerate(template)) + len(result)) % 47 != 0`
hold at every observed inner-loop iteration? Report the total number of
iterations observed and the number that violated the predicate.

An invocation is one runtime call of exactly
`flask.templating.DispatchingJinjaLoader.list_templates`, counted 1-based in
chronological order from the start of the named test. Include every such
invocation caused by the test. Calls to either loader's `list_templates`
method and calls to all other functions are not target invocations. An
inner-loop iteration is one execution in the target function's own frame of
line 118, the `result.add(template)` statement inside the blueprint-template
loop. Evaluate the predicate at the line event immediately before that
line-118 statement executes, using the target frame's current local string
`template` and current local set `result`. `enumerate` uses its default
zero-based positions, `ord` and `len` have their standard Python meanings,
and all arithmetic is integer arithmetic.

Count observations across invocations in chronological execution order.
Every repeated execution counts independently; do not sort or deduplicate
observations, including iterations whose `template` value has appeared
before. `is_invariant_always_held` is true only when at least one iteration
was observed and the predicate evaluated true at every observation. If zero
iterations are observed, report false with both integer counts equal to zero.

Line numbers are absolute, 1-based source line numbers in the named
repo-relative file as it exists in this checkout. For a multi-line statement
or expression, its line event is attributed to the line where the statement
or expression begins. The function's `def` line, decorator lines, and
docstring-only lines are not iterations.

Return exactly one JSON object with exactly these keys in this order:
`is_invariant_always_held`, `total_iterations_observed`, and
`violating_iteration_count`. The first value is a JSON boolean and the other
two are JSON integers written as base-10 numbers, not strings. There is no
sorting or tie-breaking of answer fields beyond the stated fixed key order.
There are no serialized function names, exception names, local values,
Python `repr` or `str` values, containers, empty strings, or null values in
the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_locals(raw: str, line_number: int) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(f"cannot parse locals on trace line {line_number}: {error}")
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in parsed.items()
    ):
        fail(f"unexpected locals representation on trace line {line_number}")
    return parsed


def parse_runtime_value(raw: str, variable: str, line_number: int):
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        fail(
            f"cannot parse {variable} on trace line {line_number}: {error}"
        )


def compute_answer(trace_path: Path) -> dict[str, object]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    total_iterations = 0
    violations = 0
    active = False
    state: dict[str, str] = {}
    shadow_result: set | None = None

    with trace_path.open(encoding="utf-8") as trace_file:
        for trace_line_number, raw_line in enumerate(trace_file, 1):
            match = EVENT_RE.search(raw_line.rstrip("\n"))
            if match is None or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            event = match.group("event")
            changed = parse_locals(match.group("locals"), trace_line_number)

            if event == "call":
                if active:
                    fail("encountered a nested target call")
                active = True
                state = dict(changed)
                shadow_result = None
            else:
                if not active:
                    fail(f"encountered target {event} event outside an invocation")
                state.update(changed)

            if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
                if "template" not in state or "result" not in state:
                    fail(
                        f"missing predicate locals at trace line {trace_line_number}"
                    )
                template = parse_runtime_value(
                    state["template"], "template", trace_line_number
                )
                if not isinstance(template, str):
                    fail(f"template is not a string at trace line {trace_line_number}")

                if shadow_result is None:
                    initial_result = parse_runtime_value(
                        state["result"], "result", trace_line_number
                    )
                    if not isinstance(initial_result, set):
                        fail(f"result is not a set at trace line {trace_line_number}")
                    shadow_result = initial_result

                weighted_template = sum(
                    (position + 1) * ord(character)
                    for position, character in enumerate(template)
                )
                total_iterations += 1
                if (weighted_template + len(shadow_result)) % 47 == 0:
                    violations += 1
                shadow_result.add(template)

            if event == "return":
                active = False
                state = {}
                shadow_result = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active:
        fail("trace ended while a target invocation was active")

    return {
        "is_invariant_always_held": total_iterations > 0 and violations == 0,
        "total_iterations_observed": total_iterations,
        "violating_iteration_count": violations,
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": compute_answer(args.trace_log),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
