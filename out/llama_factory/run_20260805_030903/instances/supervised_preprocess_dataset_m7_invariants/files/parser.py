#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/data/processor/supervised.py"
TARGET_FUNC = "llamafactory.data.processor.supervised.preprocess_dataset"
OBSERVATION_LINE = 182

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/supervised_preprocess_dataset_m7_invariants/files/testcase.py::"
    "TestPackedSupervisedRuntime::test_seeded_indirect_packing`. Consider only runtime events "
    "from the exact function "
    "`llamafactory.data.processor.supervised.PackedSupervisedDatasetProcessor.preprocess_dataset` "
    "defined in `src/llamafactory/data/processor/supervised.py`; exclude every other function "
    "and frame. An invocation is one runtime entry into that exact function during the complete "
    "test run, and invocations are numbered 1-based in chronological entry order. Observe the "
    "target frame at each Python `line` execution event for absolute, 1-based source line 182, "
    "the line whose statement begins `if len(packed_input_ids) <`. A line execution event is the "
    "event immediately before Python executes the statement or expression beginning on that "
    "line; here it occurs after the current outer `for knapsack in knapsacks` iteration's inner "
    "`for i, length in enumerate(knapsack)` loop has finished and before the line-182 condition "
    "is evaluated. The `def` line, comments, and all other source lines are not observations. "
    "For completeness, on a multi-line statement a line event belongs to the absolute line where "
    "the executed statement or expression begins, although the observed statement here is on one "
    "line. Define iteration N as the Nth such line-182 event across all target invocations in "
    "chronological order, starting at 1. Count every observation, including repeated states; do "
    "not sort or deduplicate observations, and no tie-breaker is needed because execution order "
    "is total. At every observation, evaluate this candidate predicate verbatim against the "
    "current target-frame local using ordinary Python semantics: "
    "`len(packed_input_ids) % 9 == 0`. A violating iteration is an observation where that "
    "predicate evaluates to false. `is_invariant_always_held` is true exactly when the predicate "
    "is true at every observation. If there are zero observations, the invariant is not "
    "evaluable: report `is_invariant_always_held` as false and both counts as 0. Return exactly "
    "one JSON object with exactly these keys and no others: `is_invariant_always_held` as a JSON "
    "boolean, `total_iterations_observed` as a non-negative JSON integer equal to the number of "
    "observations, and `violating_iteration_count` as a non-negative JSON integer equal to the "
    "number of false evaluations. These are scalar JSON values, not `repr()` or `str()` strings; "
    "there are no reported container values, names, exceptions, line numbers, empty strings, "
    "nulls, omitted values, or additional ordering rules."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/processor/supervised\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b(?P<rest>.*)"
)
LOCALS_RE = re.compile(r" locals=(?P<locals>\{.*\})$")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def read_target_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    match.group("rest"),
                )
            )
    return events


def parse_changed_locals(rest):
    match = LOCALS_RE.search(rest)
    if not match:
        fail(f"cannot parse locals from target event: {rest!r}")
    try:
        changed = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot decode target locals: {exc}")
    if not isinstance(changed, dict):
        fail(f"decoded target locals are not a dictionary: {changed!r}")
    return changed


def evaluate_invariant(events):
    call_count = sum(event == "call" for event, _line, _rest in events)
    if call_count == 0:
        fail(f"trace contains no call events for {TARGET_FUNC}")

    current_locals = {}
    observations = []
    active = False
    for event, line, rest in events:
        if event == "call":
            current_locals = {}
            active = True

        changed = parse_changed_locals(rest)
        current_locals.update(changed)

        if event == "line" and line == OBSERVATION_LINE:
            if not active:
                fail("observed line 182 outside an active target invocation")
            value_repr = current_locals.get("packed_input_ids")
            if value_repr is None:
                fail("packed_input_ids is unavailable at a line-182 observation")
            try:
                packed_input_ids = ast.literal_eval(value_repr)
            except (SyntaxError, ValueError) as exc:
                fail(f"cannot decode packed_input_ids at line 182: {exc}")
            if not isinstance(packed_input_ids, list):
                fail("packed_input_ids at line 182 is not a list")
            observations.append(len(packed_input_ids) % 9 == 0)

        if event == "return":
            active = False
            current_locals = {}

    violating_count = sum(not held for held in observations)
    return {
        "is_invariant_always_held": bool(observations) and violating_count == 0,
        "total_iterations_observed": len(observations),
        "violating_iteration_count": violating_count,
    }


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = read_target_events(trace_path)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": evaluate_invariant(events),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
