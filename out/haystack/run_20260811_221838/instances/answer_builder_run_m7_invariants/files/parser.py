#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/components/builders/answer_builder.py"
TARGET_FUNC = "haystack.components.builders.answer_builder.run"
MAIN_LINE = 159
EXCEPT_LINE = 150

PREDICATES = {
    'answer_string != ""',
    "idx % 2 == 0",
    "isinstance(reply, ChatMessage)",
    "len(given_metadata) >= 2",
    "len(given_metadata) <= 5",
    "len(reference_idxs) <= 2",
}

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* "
    r"locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run every test method in `TestAnswerBuilderRunInvariants` from \
`haystack_qa/answer_builder_run_m7_invariants/files/testcase.py` (every pytest \
node whose id starts with \
`haystack_qa/answer_builder_run_m7_invariants/files/testcase.py::TestAnswerBuilderRunInvariants::test_`). \
Run each such node exactly once in pytest's displayed collection order, with \
no selective repetition, and aggregate observations across ALL test methods \
in that class.

For the exact function frame \
`haystack.components.builders.answer_builder.AnswerBuilder.run` in \
`haystack/components/builders/answer_builder.py`, evaluate the following six \
candidate predicates verbatim:

1. `answer_string != ""`
2. `idx % 2 == 0`
3. `isinstance(reply, ChatMessage)`
4. `len(given_metadata) >= 2`
5. `len(given_metadata) <= 5`
6. `len(reference_idxs) <= 2`

Evaluate predicates 1, 3, 4, and 5 at every execution-line checkpoint for \
absolute line 159, immediately before the statement beginning on that line \
executes. Evaluate predicate 6 at the same checkpoint, but only when \
`reference_idxs` is bound in the current invocation. Evaluate predicate 2 at \
every execution-line checkpoint for absolute line 150, immediately before the \
statement beginning on that line executes. A predicate is evaluated only \
when every name it uses is bound in the exact target frame at its stated \
checkpoint; an unbound-name checkpoint contributes no observation for that \
predicate. Use the variables' actual runtime values and ordinary Python \
semantics: `ChatMessage` means \
`haystack.dataclasses.chat_message.ChatMessage`.

Line numbers are absolute, 1-based lines in the named repository file as it \
exists for this run. An execution-line checkpoint occurs before the statement \
or expression beginning on that line executes; for a multi-line statement, \
the checkpoint belongs to the line where that executed statement or \
expression begins. Decorator lines, the `def` line, and non-executed docstring \
lines are not checkpoints. Count only the exact `AnswerBuilder.run` frame; \
exclude helper, comprehension, and all other nested or called frames. \
Parameters are ordinary locals. No augmented assignment or \
comprehension-local variable participates in these predicates.

An invocation is one chronological entry into the exact target function, \
numbered from 1 across the complete pytest run, although invocation numbers \
are not emitted. Each qualifying execution-line checkpoint contributes one \
observation for its predicate, including duplicate runtime states; do not \
deduplicate anything. A violation is an observation at which the predicate \
evaluates to Python `False`. `held_always` is exactly `violations == 0` when \
there is at least one observation. For a predicate with no observations, \
report `observations: 0`, `violations: 0`, and `held_always: false`.

Return exactly `{"invariant_report": [...]}`. The array contains one object \
per predicate with exactly these keys and types: `predicate` is the verbatim \
JSON string shown above, `held_always` is a JSON boolean, and `observations` \
and `violations` are JSON integers. Sort objects by `predicate` ascending in \
Unicode code-point lexicographic order. Predicate strings are unique, so \
there is no secondary tie-break; preserve all six objects."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_repr(value: str, name: str, trace_line: int):
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse {name} representation on trace line {trace_line}: {exc}")


def parse_trace(trace_path: Path) -> list[dict]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    counts = {predicate: {"observations": 0, "violations": 0} for predicate in PREDICATES}
    state = {}
    target_events = 0

    for trace_line, raw_line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        try:
            local_delta = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse target locals on trace line {trace_line}: {exc}")
        if not isinstance(local_delta, dict):
            fail(f"target locals are not a dictionary on trace line {trace_line}")

        event = match.group("event")
        if event == "call":
            state = {}
        state.update(local_delta)

        if event != "line":
            continue
        source_line = int(match.group("line"))

        evaluations = {}
        if source_line == MAIN_LINE:
            required = {"answer_string", "reply", "given_metadata"}
            if not required.issubset(state):
                fail(f"required locals missing at line {MAIN_LINE} on trace line {trace_line}")

            answer_string = parse_repr(state["answer_string"], "answer_string", trace_line)
            given_metadata = parse_repr(state["given_metadata"], "given_metadata", trace_line)
            reply_repr = state["reply"]
            try:
                reply_value = ast.literal_eval(reply_repr)
                is_chat_message = not isinstance(reply_value, str)
            except (SyntaxError, ValueError):
                is_chat_message = True

            evaluations['answer_string != ""'] = answer_string != ""
            evaluations["isinstance(reply, ChatMessage)"] = is_chat_message
            evaluations["len(given_metadata) >= 2"] = len(given_metadata) >= 2
            evaluations["len(given_metadata) <= 5"] = len(given_metadata) <= 5
            if "reference_idxs" in state:
                reference_idxs = parse_repr(state["reference_idxs"], "reference_idxs", trace_line)
                evaluations["len(reference_idxs) <= 2"] = len(reference_idxs) <= 2

        elif source_line == EXCEPT_LINE and "idx" in state:
            idx = parse_repr(state["idx"], "idx", trace_line)
            evaluations["idx % 2 == 0"] = idx % 2 == 0

        for predicate, held in evaluations.items():
            counts[predicate]["observations"] += 1
            if not held:
                counts[predicate]["violations"] += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if sum(item["observations"] for item in counts.values()) == 0:
        fail("target events contain zero predicate observations")

    report = []
    for predicate in sorted(PREDICATES):
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
    return report


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

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
        "oracle_answer": {"invariant_report": parse_trace(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
