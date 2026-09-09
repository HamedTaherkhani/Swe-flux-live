#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/train/ppo/trainer.py"
TARGET_FUNC = "llamafactory.train.ppo.trainer.batched_forward_pass"
OBSERVATION_LINE = 455
SCALAR_NAMES = ("i", "j", "start", "end")

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/trainer_batched_forward_pass_m7_invariants/files/testcase.py::"
    "TestBatchedForwardRuntime::test_seeded_step_observations`. Consider only runtime events "
    "from the exact function body "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.batched_forward_pass` defined in "
    "`src/llamafactory/train/ppo/trainer.py`; exclude its comprehension frame, its callers, "
    "callees, decorator wrapper, and every other frame. An invocation is one runtime `call` entry "
    "into that exact function body during the complete test run, and invocations are numbered "
    "1-based in chronological "
    "entry order. Observe the target frame at each Python `line` execution event for absolute, "
    "1-based source line 455, whose statement begins `masks[j, :start] = 0`, as the named file "
    "exists in the repository. A line event occurs immediately before Python executes the "
    "statement or expression beginning on that line, so evaluate using the current local values "
    "at that instant. For a multi-line statement, an event belongs to the absolute line where "
    "the executed statement or expression begins; the observed statement is single-line. "
    "Decorator lines, the `def` line, the docstring, comments, and all other source lines are "
    "not observations. Define iteration N as the Nth such line-455 event across all target "
    "invocations in chronological execution order, starting at 1. Count every observation, "
    "including repeated states; do not sort or deduplicate them, and no tie-breaker is needed "
    "because chronological execution order is total. At every observation, evaluate this one "
    "candidate predicate verbatim against the target frame's integer locals with ordinary Python "
    "semantics: `end - start >= 1 + ((i * i + j + start) % 5)`. A violating iteration is an "
    "observation at which that predicate evaluates to false. `is_invariant_always_held` is true "
    "exactly when the predicate is true at every observation. If there are zero observations, "
    "the invariant is not evaluable: report `is_invariant_always_held` as false and both counts "
    "as 0. Return exactly one JSON object with exactly these keys and no others: "
    "`is_invariant_always_held` as a JSON boolean, `total_iterations_observed` as a non-negative "
    "JSON integer equal to the number of observations, and `violating_iteration_count` as a "
    "non-negative JSON integer equal to the number of false evaluations. These are scalar JSON "
    "values, not `repr()` or `str()` strings. There are no reported containers, names, exception "
    "values, line-number values, empty strings, nulls, omitted values, sorting rules, or other "
    "serialization conventions."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/train/ppo/trainer\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b(?P<rest>.*)"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def scalar_change(rest, name):
    match = re.search(rf"(?:^|[{{,]\s*)'{name}': '(-?\d+)'(?:,|}})", rest)
    return int(match.group(1)) if match else None


def evaluate(trace_path):
    target_event_count = 0
    call_count = 0
    state = {}
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

        for name in SCALAR_NAMES:
            value = scalar_change(rest, name)
            if value is not None:
                state[name] = value

        if event == "line" and line == OBSERVATION_LINE:
            missing = sorted(set(SCALAR_NAMES) - state.keys())
            if missing:
                fail(f"line {OBSERVATION_LINE} observation lacks locals: {missing}")
            held = state["end"] - state["start"] >= 1 + (
                (state["i"] * state["i"] + state["j"] + state["start"]) % 5
            )
            observations.append(held)

        if event == "return":
            state = {}

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
