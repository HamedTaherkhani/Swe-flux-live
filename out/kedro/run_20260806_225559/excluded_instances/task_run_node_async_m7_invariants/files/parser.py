from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/runner/task.py"
TARGET_FUNC = "kedro.runner.task.Task._run_node_async"
LOOP_HEADER_LINE = 221
INVOCATION = 1
PREDICATE_DIVISOR = 17
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\blocals=(?P<locals>\{.*\})$")

QUESTION = """Run the pytest test
`kedro_qa/task_run_node_async_m7_invariants/files/testcase.py::TestAsyncNodeOutputInvariants::test_seeded_multi_output_pipeline`
against this repository. For the first invocation of
`kedro.runner.task.Task._run_node_async` in `kedro/runner/task.py`, consider
the `for name, data in outputs.items()` loop whose header starts at line 221.
At every iteration, observe the target frame on the Python `line` event for
line 222, the loop body's first statement, after Python has assigned that
iteration's `name` and `data`. Did the candidate predicate
`data % 17 != 0` hold at every observation? Also report the total number of
iterations observed and the number for which that predicate was false.

Count target invocations 1-based in chronological order. An invocation is one
Python `call` event whose frame is exactly
`kedro.runner.task.Task._run_node_async`; the requested invocation is the
first such call during the test run. Iteration N is the Nth Python `line`
event at line 222 in that invocation, in execution order. Include every such
event, including iterations whose asynchronous save completes later in a
different order. Exclude `call`, `return`, and `exception` events, all other
source lines, other invocations, and events from callees, comprehensions,
worker threads, generator resumptions, or any frame other than that exact
target frame. Do not sort or deduplicate observations: every qualifying line
event contributes once.

Evaluate the predicate using the actual Python integer bound to local variable
`data` at each qualifying event; `%` and `!=` have their ordinary Python
semantics. “Held at every observation” means the predicate was true for every
qualifying event. `violating_iteration_count` counts events where it was
false, and `total_iterations_observed` counts all qualifying events. If there
are zero qualifying observations, the invariant is not evaluable and no
answer object should be reported; do not treat it as vacuously true.

Line numbers are absolute, 1-based source line numbers in the named file as it
exists in this repository. For a multi-line statement or expression, a Python
`line` event is attributed to the line where the executed statement or
expression begins. The function's `def` line, decorator lines, and docstring
lines cannot count because only line 222 events count.

Return exactly one JSON object with exactly these keys and value types:
`{"is_invariant_always_held": "bool", "total_iterations_observed": "int",
"violating_iteration_count": "int"}`. The quoted type names here are schema
placeholders: emit `is_invariant_always_held` as a JSON boolean (`true` or
`false`, not a string or Python spelling), and emit both counts as JSON
integers. The result is computed in event order, but all three leaves are
scalars, so there is no value formatting via `repr()` or `str()`, no null or
empty-value representation, and no sorting, tie-breaking, or deduplication
step."""


def _observation_line(source_path: Path) -> int:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target_class = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == "Task"
        ),
        None,
    )
    if target_class is None:
        raise RuntimeError(f"Task class not found in {source_path}")
    target_function = next(
        (
            item
            for item in target_class.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "_run_node_async"
        ),
        None,
    )
    if target_function is None:
        raise RuntimeError(f"Task._run_node_async not found in {source_path}")
    loops = [
        item
        for item in ast.walk(target_function)
        if isinstance(item, ast.For) and item.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1 or not loops[0].body:
        raise RuntimeError(
            f"expected exactly one non-empty for loop at line {LOOP_HEADER_LINE}"
        )
    return loops[0].body[0].lineno


def _parse_changed_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if not match:
        raise RuntimeError(f"target event has no parseable locals mapping: {raw_line}")
    value = ast.literal_eval(match.group("locals"))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise RuntimeError(f"invalid traced locals mapping: {raw_line}")
    return value


def _observed_data(trace_path: Path, observation_line: int) -> list[int]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    in_requested_invocation = False
    current_locals: dict[str, str] = {}
    observed: list[int] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file")
            .replace("\\", "/")
            .endswith(f"/{TARGET_FILE}")
        ):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation_number += 1
            in_requested_invocation = invocation_number == INVOCATION
            current_locals = _parse_changed_locals(raw_line)
            continue
        if not in_requested_invocation:
            continue
        if event in {"line", "return", "exception"}:
            current_locals.update(_parse_changed_locals(raw_line))
        if event == "line" and int(match.group("line")) == observation_line:
            if "data" not in current_locals:
                raise RuntimeError("observation has no local variable named 'data'")
            data = ast.literal_eval(current_locals["data"])
            if isinstance(data, bool) or not isinstance(data, int):
                raise RuntimeError(
                    f"observed data is not a Python integer: {current_locals['data']}"
                )
            observed.append(data)
        if event == "return":
            in_requested_invocation = False

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations"
        )
    if not observed:
        raise RuntimeError(
            f"invocation {INVOCATION} contains zero observations at line "
            f"{observation_line}"
        )
    return observed


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    observation_line = _observation_line(Path.cwd() / TARGET_FILE)
    if observation_line != 222:
        raise RuntimeError(
            f"loop body observation line is {observation_line}, expected 222"
        )
    observations = _observed_data(args.trace_log, observation_line)
    violations = sum(data % PREDICATE_DIVISOR == 0 for data in observations)
    answer = {
        "is_invariant_always_held": violations == 0,
        "total_iterations_observed": len(observations),
        "violating_iteration_count": violations,
    }
    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
