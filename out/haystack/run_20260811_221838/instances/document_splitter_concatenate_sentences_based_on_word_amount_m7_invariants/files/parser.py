#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FUNC = (
    "haystack.components.preprocessors.document_splitter."
    "DocumentSplitter._concatenate_sentences_based_on_word_amount"
)
TRACE_FUNC = "haystack.components.preprocessors.document_splitter._concatenate_sentences_based_on_word_amount"
PRIMARY_LINE = 437
UNREACHED_LINE = 407

PREDICATES = {
    "(chunk_word_count + sentence_idx) % 4 != 0": PRIMARY_LINE,
    "chunk_word_count + next_sentence_word_count <= split_length + split_overlap": PRIMARY_LINE,
    "chunk_word_count <= 30": PRIMARY_LINE,
    "next_sentence_word_count <= 30": PRIMARY_LINE,
    "split_overlap < split_length": UNREACHED_LINE,
}

QUESTION = """Run every test method in `haystack_qa/document_splitter_concatenate_sentences_based_on_word_amount_m7_invariants/files/testcase.py::TestDocumentSplitterRuntimeInvariants` and report runtime invariants for `haystack.components.preprocessors.document_splitter.DocumentSplitter._concatenate_sentences_based_on_word_amount` in `haystack/components/preprocessors/document_splitter.py`. The answer aggregates all 12 `test_...` methods in that class. A test is identified by its full pytest id `haystack_qa/document_splitter_concatenate_sentences_based_on_word_amount_m7_invariants/files/testcase.py::TestDocumentSplitterRuntimeInvariants::<method_name>`; consider those ids in ascending string order. An invocation is one entry into the target function, numbered from 1 in chronological execution order within that run.

Evaluate these five candidate predicates verbatim:

1. `(chunk_word_count + sentence_idx) % 4 != 0`
2. `chunk_word_count + next_sentence_word_count <= split_length + split_overlap`
3. `chunk_word_count <= 30`
4. `next_sentence_word_count <= 30`
5. `split_overlap < split_length`

For predicates 1-4, an observation is each execution of the `if` statement beginning at absolute, 1-based line 437 of the named repository file, immediately before that statement's condition is evaluated. Evaluate the predicate from that target invocation's local values at that moment. For predicate 5, an observation is each execution of absolute, 1-based line 407, immediately before the expression beginning on that line is evaluated. A multi-line statement is identified by the line where its statement or expression begins; decorator and `def` lines do not count as observation points. Sum observations across every target invocation made by all test methods. Do not deduplicate repeated observations.

Return exactly `{"invariant_report": [...]}`. The list has exactly one object per candidate, with exactly these keys and types: `predicate` is the verbatim string above, `observations` is an integer count of evaluations, `violations` is an integer count for which the predicate evaluated to false, and `held_always` is a JSON boolean equal to `violations == 0` when at least one observation exists. If a predicate has zero observations, report `observations: 0`, `violations: 0`, and `held_always: false`. Sort entries by the full `predicate` string in ascending Unicode code-point order. Predicate strings are unique, so no tie-break is needed and no entries are removed. Integers are emitted as JSON numbers and booleans as lowercase JSON `true` or `false`; no local value itself is serialized into the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_changed_locals(raw: str, line_number: int) -> dict:
    try:
        outer = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals dictionary on trace line {line_number}: {exc}")
    if not isinstance(outer, dict):
        fail(f"locals payload on trace line {line_number} is not a dictionary")

    parsed = {}
    for name, representation in outer.items():
        if not isinstance(representation, str):
            fail(f"local {name!r} on trace line {line_number} has a non-string representation")
        try:
            parsed[name] = ast.literal_eval(representation)
        except (SyntaxError, ValueError):
            parsed[name] = representation
    return parsed


def evaluate(predicate: str, state: dict) -> bool:
    required = {
        "(chunk_word_count + sentence_idx) % 4 != 0": {"chunk_word_count", "sentence_idx"},
        "chunk_word_count + next_sentence_word_count <= split_length + split_overlap": {
            "chunk_word_count",
            "next_sentence_word_count",
            "split_length",
            "split_overlap",
        },
        "chunk_word_count <= 30": {"chunk_word_count"},
        "next_sentence_word_count <= 30": {"next_sentence_word_count"},
        "split_overlap < split_length": {"split_overlap", "split_length"},
    }[predicate]
    missing = sorted(required - state.keys())
    if missing:
        fail(f"missing locals for predicate {predicate!r}: {missing}")

    if predicate == "(chunk_word_count + sentence_idx) % 4 != 0":
        return (state["chunk_word_count"] + state["sentence_idx"]) % 4 != 0
    if predicate == "chunk_word_count + next_sentence_word_count <= split_length + split_overlap":
        return (
            state["chunk_word_count"] + state["next_sentence_word_count"]
            <= state["split_length"] + state["split_overlap"]
        )
    if predicate == "chunk_word_count <= 30":
        return state["chunk_word_count"] <= 30
    if predicate == "next_sentence_word_count <= 30":
        return state["next_sentence_word_count"] <= 30
    if predicate == "split_overlap < split_length":
        return state["split_overlap"] < state["split_length"]
    fail(f"unknown predicate: {predicate}")
    return False


def build_answer(trace_path: Path) -> dict:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    reports = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in PREDICATES
    }
    state = {}
    target_events = 0
    event_pattern = re.compile(
        rf"^[^\n]*?document_splitter\.py:(?P<line>\d+) {re.escape(TRACE_FUNC)} "
        rf"event=(?P<event>call|line|return|exception)(?: .*?)? locals=(?P<locals>\{{.*\}})$"
    )

    for trace_line_number, trace_line in enumerate(text.splitlines(), start=1):
        match = event_pattern.match(trace_line)
        if match is None:
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            state = {}
        state.update(parse_changed_locals(match.group("locals"), trace_line_number))

        if event == "line":
            source_line = int(match.group("line"))
            for predicate, observation_line in PREDICATES.items():
                if source_line != observation_line:
                    continue
                reports[predicate]["observations"] += 1
                if not evaluate(predicate, state):
                    reports[predicate]["violations"] += 1

        if event == "return":
            state = {}

    if target_events == 0:
        fail(f"trace log contains zero events for {TARGET_FUNC}")

    invariant_report = []
    for predicate in sorted(PREDICATES):
        observations = reports[predicate]["observations"]
        violations = reports[predicate]["violations"]
        invariant_report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": invariant_report}


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
        "oracle_answer": build_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
