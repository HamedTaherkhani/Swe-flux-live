#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/full_train.py"
TARGET_FUNC = "instructlab.model.full_train.train"
INVOCATION = 1
OBSERVATION_LINE = 235
OCCURRENCE = 27
VARIABLES = (
    "aggregated_values",
    "epoch",
    "loss",
    "num_loss_counted_tokens",
    "step",
)
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r".*\slocals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test `instruct_lab_qa/full_train_train_s3_state/files/testcase.py::TestFullPipeline::test_seeded_batches` and consider `instructlab.model.full_train.train` in `src/instructlab/model/full_train.py`. For the first invocation of that function during the complete test run, what are the values of the local variables `aggregated_values`, `epoch`, `loss`, `num_loss_counted_tokens`, and `step` immediately after line 235 has executed for the 27th time?

An invocation is one Python `call` of exactly `instructlab.model.full_train.train`, counted 1-based in chronological order over the complete test run; calls of nested functions, callees, or any other frame do not create target invocations. Use invocation 1. An execution of line 235 means execution in that invocation's own frame of the single-line statement beginning there, `inner_pb.update(1)`. Count these executions 1-based in chronological order, including executions reached from different loop iterations, and do not deduplicate them. “Immediately after” means the state after that statement has completed but before the next source statement in the target frame executes; activity inside `inner_pb.update` is not part of the observation.

Line numbers are absolute, 1-based physical lines in the named file as it exists in the repository. Line 235 is a single-line statement, so multi-line statement normalization does not apply. The function's `def` line, decorators, docstring lines, and events in callees or other frames cannot count as executions of line 235.

Return exactly one JSON object with the shape `{"observed_state": [{"value": "str", "variable": "str"}]}`. The actual `observed_state` list must contain one object for each of the five named variables, ordered by the variable name in ascending lexicographic Unicode code-point order; there are no ties, and no entries are deduplicated. In each object, `variable` is the variable's exact source identifier and `value` is the Python `repr()` string of its value at the observation point, not `str()` and not a JSON rendering of that value. For a container, report the `repr()` of the whole container, so strings retain quotes and Python spellings such as `None` and `True` remain inside the JSON string; for example, a hypothetical list would be represented as `"['example', None]"`. If a repr contains a newline, that newline is part of the value and is encoded by JSON in the normal way. All five locals exist at this point, so JSON `null`, an empty string, and an absent entry are not substitutes for any value. Function-name, callee-name, and exception-type serialization conventions do not apply because none are reported."""


def parse_observed_state(trace_path: Path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    selected = False
    selected_finished = False
    occurrences = 0
    pending_observation = False
    state = {}
    observed = None

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed.items()
        ):
            raise RuntimeError("target locals are not a string-to-string mapping")

        if event == "call":
            invocation_number += 1
            selected = invocation_number == INVOCATION
            if selected:
                state = dict(changed)
            continue
        if not selected:
            continue

        state.update(changed)
        if pending_observation:
            observed = dict(state)
            pending_observation = False

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            occurrences += 1
            if occurrences == OCCURRENCE:
                pending_observation = True

        if event == "return":
            selected = False
            selected_finished = True

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations; "
            f"cannot select invocation {INVOCATION}"
        )
    if not selected_finished:
        raise RuntimeError(f"invocation {INVOCATION} has no return event")
    if occurrences < OCCURRENCE:
        raise RuntimeError(
            f"line {OBSERVATION_LINE} executed only {occurrences} times; "
            f"cannot select occurrence {OCCURRENCE}"
        )
    if observed is None:
        raise RuntimeError("observation point was not followed by a target-frame event")

    missing = sorted(set(VARIABLES) - observed.keys())
    if missing:
        raise RuntimeError(f"observation is missing locals: {missing}")
    return [
        {"value": observed[variable], "variable": variable}
        for variable in sorted(VARIABLES)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {
            "observed_state": parse_observed_state(args.trace_log)
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
