#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/eval/evaluator.py"
TARGET_FUNC = "llamafactory.eval.evaluator.eval"
OBSERVATION_LINE = 134

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/evaluator_eval_m7_invariants/files/testcase.py::"
    "TestEvaluatorRuntimeInvariants::test_seeded_public_entrypoint_subject_matrix`. "
    "Consider only runtime events from the exact function body "
    "`llamafactory.eval.evaluator.Evaluator.eval` defined in "
    "`src/llamafactory/eval/evaluator.py`; exclude its callers, callees, the "
    "dictionary-comprehension frame created on line 134, the decorator machinery, and every "
    "other frame. An invocation is one runtime entry into that exact function body during the "
    "complete test run, and invocations are numbered 1-based in chronological entry order. "
    "Observe the target frame at each Python `line` execution event for absolute, 1-based "
    "source line 134, whose statement begins `results[subject] =`, as the named file exists in "
    "the repository. A line event occurs immediately before Python executes the statement or "
    "expression beginning on that line; thus this observation occurs once in each completed "
    "outer subject-loop iteration, after `outputs` and `labels` have been populated and before "
    "the result dictionary entry is assigned. For a multi-line statement, an event belongs to "
    "the absolute line on which the executed statement or expression begins; the observed "
    "statement begins and ends on line 134. Decorator lines, the `def` line, comments, and all "
    "other source lines are not observations. Define iteration N as the Nth such line-134 event "
    "across all target invocations in chronological execution order, starting at 1. Count every "
    "observation, including repeated states; do not sort or deduplicate observations, and no "
    "tie-breaker is needed because chronological execution order is total. At every observation, "
    "evaluate this one candidate predicate verbatim against the target frame's current Python "
    "locals using ordinary Python semantics: "
    "`sum(output == label for output, label in zip(outputs, labels)) == len(labels) or "
    "sum(map(ord, subject)) % 12 != 4`. Here `zip`, `sum`, `map`, `ord`, and `len` have their "
    "ordinary Python built-in meanings, Python's `==`, `%`, and `!=` comparisons bind more "
    "tightly than `or`, and the generator variable names `output` and `label` are local only to "
    "that predicate. A violating iteration is an observation at "
    "which the predicate evaluates to false. `is_invariant_always_held` is true exactly when "
    "the predicate is true at every observation. If there are zero observations, the invariant "
    "is not evaluable: report `is_invariant_always_held` as false and both counts as 0. Return "
    "exactly one JSON object with exactly these keys and no others: "
    "`is_invariant_always_held` as a JSON boolean, `total_iterations_observed` as a non-negative "
    "JSON integer equal to the number of observations, and `violating_iteration_count` as a "
    "non-negative JSON integer equal to the number of false evaluations. These are scalar JSON "
    "values, not `repr()` or `str()` strings. There are no reported containers, function or "
    "exception names, source-line values, empty strings, nulls, omitted values, sorting rules, "
    "or other serialization conventions."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/eval/evaluator\.py):(?P<line>\d+) "
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


def decode_local(state, name):
    if name not in state:
        fail(f"line {OBSERVATION_LINE} observation lacks local {name!r}")
    try:
        return ast.literal_eval(state[name])
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot decode local {name!r}: {exc}")


def evaluate(trace_path):
    target_event_count = 0
    call_count = 0
    state = {}
    active = False
    observations = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_event_count += 1
        event = match.group("event")
        line = int(match.group("line"))
        rest = match.group("rest")

        if event == "call":
            call_count += 1
            state = {}
            active = True

        state.update(parse_changed_locals(rest))

        if event == "line" and line == OBSERVATION_LINE:
            if not active:
                fail(f"line {OBSERVATION_LINE} observed outside an active invocation")
            outputs = decode_local(state, "outputs")
            labels = decode_local(state, "labels")
            subject = decode_local(state, "subject")
            if not isinstance(outputs, list) or not isinstance(labels, list):
                fail("outputs and labels must decode as lists")
            if not isinstance(subject, str):
                fail("subject must decode as a string")
            held = (
                sum(output == label for output, label in zip(outputs, labels))
                == len(labels)
                or sum(map(ord, subject)) % 12 != 4
            )
            observations.append(held)

        if event == "return":
            state = {}
            active = False

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if call_count == 0:
        fail(f"trace contains no call events for {TARGET_FUNC}")

    violations = sum(not held for held in observations)
    return {
        "is_invariant_always_held": bool(observations) and violations == 0,
        "total_iterations_observed": len(observations),
        "violating_iteration_count": violations,
    }


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": evaluate(trace_path),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
