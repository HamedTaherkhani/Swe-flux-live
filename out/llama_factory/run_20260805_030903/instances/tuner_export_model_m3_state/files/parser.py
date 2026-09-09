#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "llamafactory.train.tuner.export_model"
QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/tuner_export_model_m3_state/files/testcase.py::"
    "TestExportModelProgramState::test_seeded_webui_export_matrix`. Across every invocation of "
    "`llamafactory.train.tuner.export_model` in `src/llamafactory/train/tuner.py` during that "
    "complete test run, report the sorted set of distinct values of the three-variable state "
    "tuple `(tokenizer_module, tokenizer, processor)` at executed-line observation points. An "
    "invocation is one runtime call of that exact function, numbered 1-based in chronological "
    "order, although invocation numbers are not included in the answer. An executed-line "
    "observation point is the state of the target function's own frame immediately before each "
    "executed source line begins; include a point only when all three named locals are already "
    "bound. Each local retains its latest value until it is rebound, and in-place mutations of "
    "the dictionary held by `tokenizer_module`, of objects nested in it, or of either other "
    "named object are visible at subsequent points without requiring rebinding. Include points "
    "from all invocations, but exclude call, return, and exception events and exclude all "
    "callee, generator, and comprehension frames. Line numbers, if used to reproduce the "
    "observations, are absolute 1-based line numbers in the named repository file. For a "
    "multi-line statement or expression, count each line for which CPython emits a line "
    "execution event, with state observed before that line's expression executes; the "
    "function's `def` line and any decorator or docstring lines are not observation points. At "
    "each included point, construct a Python tuple in exactly the displayed order from the "
    "current whole objects, after all mutations completed before that point, and apply Python "
    "`repr()` to the whole tuple. This uses each object's runtime `repr` recursively: preserve "
    "tuple/list order, dictionary insertion order, quote and escape choices, and Python "
    "spellings such as `None`, `True`, and `False`; do not convert nested values to JSON. For "
    "example, a different state tuple `({'sample': [2]}, 'x', None)` would be represented by "
    "the JSON string `\"({'sample': [2]}, 'x', None)\"`. Remove duplicate repr strings globally "
    "across all observation points and invocations, then sort the remaining strings in "
    "ascending lexicographic order using Python string comparison (Unicode code-point order); "
    "there is no secondary tie-breaker after deduplication. Return exactly one JSON object with "
    "the key `unique_values`; its value is a flat JSON array of JSON strings containing the "
    "complete Python repr strings. Every observation is represented by a string: JSON null, an "
    "absent key, and an empty JSON string are not substitutes for a repr value."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/train/tuner\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.*?"
    r"locals=(?P<locals>\{.*\})$"
)
VARIABLE_NAMES = ("tokenizer_module", "tokenizer", "processor")


def parse_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_locals(raw_locals, trace_line_number):
    try:
        parsed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals at trace line {trace_line_number}: {exc}")
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        fail(f"locals at trace line {trace_line_number} are not a string-to-string dictionary")
    return parsed


def main():
    args = parse_cli()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_count = 0
    current_locals = {}
    observed_values = set()

    for trace_line_number, raw_line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        changed_locals = parse_locals(match.group("locals"), trace_line_number)
        if event == "call":
            invocation_count += 1
            current_locals = dict(changed_locals)
            continue

        current_locals.update(changed_locals)
        if event != "line" or not all(name in current_locals for name in VARIABLE_NAMES):
            continue

        if any(current_locals[name].endswith("...") for name in VARIABLE_NAMES):
            fail(f"state component is truncated at trace line {trace_line_number}")
        try:
            state = tuple(ast.literal_eval(current_locals[name]) for name in VARIABLE_NAMES)
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot reconstruct state tuple at trace line {trace_line_number}: {exc}")
        observed_values.add(repr(state))

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")
    if len(observed_values) < 8:
        fail(f"expected at least 8 distinct state values, observed {len(observed_values)}")

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(observed_values)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
