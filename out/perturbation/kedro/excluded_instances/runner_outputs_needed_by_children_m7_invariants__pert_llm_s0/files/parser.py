#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/runner/runner.py"
TARGET_FUNC = "kedro.runner.runner._outputs_needed_by_children"
OBSERVATION_LINE = 667
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\slocals=(?P<locals>\{.*\})$")


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_local_changes(raw_line):
    match = LOCALS_RE.search(raw_line)
    if not match:
        fail("target trace event has no parseable locals mapping")
    try:
        changes = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals mapping: {exc}")
    if not isinstance(changes, dict):
        fail("target locals payload is not a dictionary")
    return changes


def decode_repr(value, variable):
    if not isinstance(value, str):
        fail(f"trace representation for {variable} is not a string")
    if value.endswith("..."):
        fail(f"trace representation for {variable} was truncated")
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not decode repr for {variable}: {exc}")


def evaluate_trace(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    frame_locals = None
    total_iterations = 0
    violations = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.match(raw_line)
        if not event_match:
            continue
        normalized_file = event_match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue
        if event_match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = event_match.group("event")
        line = int(event_match.group("line"))
        changes = parse_local_changes(raw_line)

        if event == "call":
            target_calls += 1
            frame_locals = {}
        if frame_locals is None:
            fail("encountered a target event outside an active invocation")
        frame_locals.update(changes)

        if event == "line" and line == OBSERVATION_LINE:
            if "dataset" not in frame_locals:
                fail("dataset is unbound at an observation event")
            dataset = decode_repr(frame_locals["dataset"], "dataset")
            if not isinstance(dataset, str):
                fail("dataset did not decode to str")
            total_iterations += 1
            predicate_holds = (
                sum(ord(character) for character in dataset) % 127 != 5
            )
            if not predicate_holds:
                violations += 1

        if event == "return":
            frame_locals = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")

    return {
        "is_invariant_always_held": total_iterations > 0 and violations == 0,
        "total_iterations_observed": total_iterations,
        "violating_iteration_count": violations,
    }


def build_question():
    return (
        "Run the pytest test "
        "`kedro_qa/runner_outputs_needed_by_children_m7_invariants/files/"
        "testcase.py::TestOutputsNeededByChildrenInvariants::"
        "test_seeded_existing_fanout_outputs`. During the complete test run, "
        "consider every invocation of "
        "`kedro.runner.runner._outputs_needed_by_children` in "
        "`kedro/runner/runner.py`. At every iteration observation defined below, "
        "did the candidate predicate "
        "`sum(ord(character) for character in dataset) % 127 != 5` hold?\n\n"
        "An invocation is one Python call of the target function, numbered 1-based "
        "in chronological call order. An iteration observation is one Python line "
        "event in the target function's own frame at absolute line 667, the line "
        "where the `if _is_dataset_ephemeral_or_missing(dataset, catalog):` "
        "statement begins. Count observations globally across all invocations in "
        "chronological event order: iteration N is the Nth such line-667 event. "
        "The event observes locals immediately before that `if` statement executes, "
        "after the inner `for dataset in shared_datasets` loop has bound `dataset`; "
        "evaluate the predicate using that current Python string value. Each event "
        "counts separately, even if a value were repeated; do not deduplicate or "
        "sort observations. Exclude call, return, and exception events, every line "
        "event at any other line, and all callee, generator, and comprehension "
        "frames.\n\n"
        "Line numbers are absolute and 1-based in the named repository file as it "
        "exists for this test. For a multi-line statement or expression, a line "
        "event belongs to the line where that currently executing statement or "
        "expression begins. The target's `def` line, docstring line, and any "
        "decorator line are not observations because only line 667 is eligible. "
        "The predicate 'held at every observation' exactly when it evaluated to "
        "Python `True` at every counted event. A violating iteration is a counted "
        "event where it evaluated to Python `False`. If there are zero observations, "
        "report `is_invariant_always_held` as JSON `false` and both counts as the "
        "JSON number `0` (the invariant is then not evaluable).\n\n"
        "Return exactly one JSON object with these three keys and no others: "
        "`is_invariant_always_held` is a JSON boolean; "
        "`total_iterations_observed` is the total number of counted events as a "
        "base-10 JSON integer; and `violating_iteration_count` is the number of "
        "counted events at which the predicate was false, also as a base-10 JSON "
        "integer. Use those keys in exactly that spelling. JSON booleans use "
        "`true`/`false`, not quoted strings or Python `True`/`False`. There are no "
        "reported strings, collections, missing values, or ordering tie-breakers; "
        "do not replace either count with an empty string or JSON `null`."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    oracle_answer = evaluate_trace(Path(args.trace_log))
    payload = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": oracle_answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} with "
        f"{oracle_answer['total_iterations_observed']} iteration observations"
    )


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
