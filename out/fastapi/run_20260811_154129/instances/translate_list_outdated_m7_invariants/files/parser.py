#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/translate.py"
TARGET_FUNC = "scripts.translate.list_outdated"
TARGET_DEF_LINE = 357
LOOP_LINE = 363
OBSERVATION_LINE = 373

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?:.*?\slocals=(?P<locals>\{.*\}))?$"
)

QUESTION = """Run the pytest test
`fastapi_qa/translate_list_outdated_m7_invariants/files/testcase.py::TestTranslationMaintenanceInvariants::test_generated_translation_maintenance`
against this repository. Consider every invocation during that test of exactly
`scripts.translate.list_outdated` whose implementation is in
`scripts/translate.py`. An invocation is one runtime `call` entry into that
exact function, counted 1-based in chronological order from the start of the
stated test. Calls and frames belonging to decorators, callers, callees,
generator resumptions, comprehensions, or any other function do not create
target invocations.

Evaluate the candidate predicate
`abs(lang_commit_datetime - en_commit_datetime) <= 5` at every execution of
the line-373 `if lang_commit_datetime < en_commit_datetime:` statement,
immediately before Python evaluates that statement. The predicate uses the
ordinary Python built-in `abs` and the current local values in the target
frame. A comparison iteration is the Nth such execution within an invocation;
combine comparison iterations from all target invocations in chronological
order. Iterations of the line-363 `for` loop that execute `continue` before
line 373 are not comparison iterations. Do not deduplicate any invocation or
line-373 execution.

Report whether this predicate held at every comparison iteration, the total
number of comparison iterations observed, and the number at which it was
false. “Held at every observation” means the predicate evaluated to Python
`True` at each included line-373 execution. If there are zero comparison
iterations, report `false`, `0`, and `0`, respectively, because the invariant
is then not evaluable.

Return exactly
`{"is_invariant_always_held": "bool", "total_iterations_observed": "int", "violating_iteration_count": "int"}`
with the type markers replaced by a JSON boolean and base-10 JSON integers;
the integer values are numbers, not quoted strings. Emit exactly those keys;
key order has no semantic significance, and there is no sorting or
tie-breaking step because only aggregate scalars are returned.

All line numbers are absolute, 1-based source line numbers in the named file
as it exists in this repository. A Python line event for a multi-line
statement belongs to the line where the executed statement or expression
begins. Here the observation is only the event for the single-line `if`
statement beginning at line 373. The function's decorator and `def` line,
the loop header at line 363, call/return boundaries, events in other frames,
and all other source lines are excluded."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_target_source(source_path: Path) -> None:
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "list_outdated"
            and node.lineno == TARGET_DEF_LINE
        ),
        None,
    )
    if target is None:
        fail(f"could not locate {TARGET_FUNC} at line {TARGET_DEF_LINE}")
    loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.For) and node.lineno == LOOP_LINE
    ]
    observations = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.If) and node.lineno == OBSERVATION_LINE
    ]
    if len(loops) != 1 or len(observations) != 1:
        fail("target source does not contain the expected loop and observation")


def parse_changed_locals(raw: str | None) -> dict[str, str]:
    if raw is None:
        fail("target event is missing its locals mapping")
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals mapping: {exc}")
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        fail("target locals mapping has an unexpected shape")
    return value


def parse_integer_repr(raw: str, variable: str) -> int:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse {variable}: {exc}")
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{variable} was not represented as an integer")
    return value


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    source_path = None
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        traced_file = match.group("file").replace("\\", "/")
        if not traced_file.endswith(TARGET_FILE):
            fail(f"target event came from unexpected file: {traced_file}")
        if source_path is None:
            source_path = Path(match.group("file"))
        target_events.append(
            (
                match.group("event"),
                int(match.group("line")),
                parse_changed_locals(match.group("locals")),
            )
        )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if source_path is None:
        fail("could not determine target source path from trace")
    validate_target_source(source_path)

    active_locals = None
    completed_invocations = 0
    total_observations = 0
    violating_observations = 0
    for event, line, changed_locals in target_events:
        if event == "call":
            if active_locals is not None:
                fail("encountered a nested target invocation")
            active_locals = {}
        elif active_locals is None:
            fail(f"encountered target {event} event outside an invocation")

        active_locals.update(changed_locals)
        if event == "line" and line == OBSERVATION_LINE:
            missing = {
                name
                for name in ("en_commit_datetime", "lang_commit_datetime")
                if name not in active_locals
            }
            if missing:
                fail(f"observation is missing locals: {sorted(missing)}")
            en_value = parse_integer_repr(
                active_locals["en_commit_datetime"], "en_commit_datetime"
            )
            lang_value = parse_integer_repr(
                active_locals["lang_commit_datetime"], "lang_commit_datetime"
            )
            total_observations += 1
            if abs(lang_value - en_value) > 5:
                violating_observations += 1
        if event == "return":
            completed_invocations += 1
            active_locals = None

    if active_locals is not None:
        fail("trace ended during an incomplete target invocation")
    if completed_invocations == 0:
        fail(f"trace contains no complete invocations of {TARGET_FUNC}")

    answer = {
        "is_invariant_always_held": (
            total_observations > 0 and violating_observations == 0
        ),
        "total_iterations_observed": total_observations,
        "violating_iteration_count": violating_observations,
    }
    output = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote oracle from {completed_invocations} complete target invocation(s) "
        f"and {total_observations} comparison iteration(s) to {out_path}"
    )


if __name__ == "__main__":
    main()
