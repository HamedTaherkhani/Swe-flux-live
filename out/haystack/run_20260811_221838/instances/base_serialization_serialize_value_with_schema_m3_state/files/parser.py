#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "haystack/utils/base_serialization.py"
TARGET_FUNC = "haystack.utils.base_serialization._serialize_value_with_schema"
RETURN_PROJECTIONS = {
    88: ("schema", "data"),
    110: ("base_schema", "pure_list"),
    117: ("schema", "pure"),
    124: ("schema", "pure"),
    130: ("schema", "payload"),
}

QUESTION = """Run all twelve `test_*` methods in `TestSerializeValueWithSchemaState` from `haystack_qa/base_serialization_serialize_value_with_schema_m3_state/files/testcase.py`: `test_01_wide_generated_mapping`, `test_02_generated_integer_list`, `test_03_generated_text_tuple`, `test_04_generated_integer_set`, `test_05_nested_matrix`, `test_06_layered_mapping`, `test_07_to_dict_object`, `test_08_attribute_object`, `test_09_generated_empty_collections`, `test_10_seeded_record_tree`, `test_11_computed_primitive_spectrum`, and `test_12_mixed_collection_tree`. The answer aggregates the complete run of every listed method. Their pytest ids are formed as the named file path, then `::TestSerializeValueWithSchemaState::`, then the method name; pytest determines their execution order.

During that run, consider every invocation of the exact function `haystack.utils.base_serialization._serialize_value_with_schema` in `haystack/utils/base_serialization.py`, including both calls made directly by the tests and recursive calls made by that function. An invocation means one `call` of that exact function and invocations are numbered from 1 in chronological order across the complete run.

Observe each invocation that completes normally at its `return` event. Exclude `call`, `line`, and `exception` events and exclude any invocation that does not reach a normal return. At each included return, form a two-element Python tuple from the live local values selected by the absolute, 1-based return-statement line: line 88 uses `(schema, data)`; line 110 uses `(base_schema, pure_list)`; line 117 uses `(schema, pure)`; line 124 uses `(schema, pure)`; and line 130 uses `(schema, payload)`. These names are source-level local-variable names. The variables named `schema`, `data`, and `base_schema` are observed after all in-place mutations performed before that return. All selected locals are bound at their stated return sites, so there is no missing-value convention and JSON `null` is not a substitute for an absent local.

For each resulting tuple, take Python's exact `repr()` of the complete tuple as one string. This is `repr()`, not `str()` and not JSON conversion: containers use the `repr()` of the whole container, nested strings retain Python quote characters, and Python spellings such as `None`, `True`, and `False` are retained. Character escaping is exactly that produced by `repr()`; for example, the repr of the tuple containing the string `left`, a newline, and the integer three is `('left\\n', 3)`, whose decoded JSON string contains a backslash followed by `n`.

Return exactly `{"unique_values": [<str>, ...]}`. Remove duplicate repr strings by exact string equality across all included returns, then sort the remaining strings in ascending Python string order (lexicographic Unicode code-point order, with no secondary tie-breaker needed after deduplication). `unique_values` is a JSON list of JSON strings and is non-empty.

Line numbers are absolute and 1-based in the named repository file as it exists for this run. For a multi-line statement or expression, an executed-line event is attributed to the line where that statement or expression begins. Here the observation points are normal return events at the five explicitly listed return-statement lines; decorator lines, the `def` line, and docstring lines are not observation points."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)(?: |$)"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def parse_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        raise ValueError(f"target event has no locals payload: {raw_line.rstrip()}")
    try:
        parsed = ast.literal_eval(raw_line.rsplit(marker, 1)[1].strip())
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"cannot parse target locals payload: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("target locals payload is not a dictionary")
    if not all(isinstance(name, str) and isinstance(value, str) for name, value in parsed.items()):
        raise ValueError("target locals payload does not map names to repr strings")
    return parsed


def parse_repr(repr_text, variable, line_number):
    if repr_text.endswith("..."):
        raise ValueError(f"repr for {variable!r} at return line {line_number} was truncated")
    try:
        return ast.literal_eval(repr_text)
    except (SyntaxError, ValueError) as error:
        raise ValueError(
            f"cannot reconstruct {variable!r} from its repr at return line {line_number}: {error}"
        ) from error


def harvest(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    calls = 0
    projected_values = []

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if (
                not match
                or match.group("func") != TARGET_FUNC
                or TARGET_FILE not in match.group("file").replace("\\", "/")
            ):
                continue

            target_events += 1
            event = match.group("event")
            if event == "call":
                calls += 1
            if event != "return":
                continue

            line_number = int(match.group("line"))
            variable_names = RETURN_PROJECTIONS.get(line_number)
            if variable_names is None:
                raise ValueError(f"unexpected normal return line for target function: {line_number}")

            locals_map = parse_locals(raw_line)
            missing = [name for name in variable_names if name not in locals_map]
            if missing:
                raise ValueError(f"return line {line_number} is missing selected locals: {missing}")
            values = tuple(
                parse_repr(locals_map[name], name, line_number)
                for name in variable_names
            )
            projected_values.append(repr(values))

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if calls == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if not projected_values:
        raise ValueError(f"trace contains no normal return event for {TARGET_FUNC}")
    return sorted(set(projected_values))


def main():
    args = parse_args()
    output_path = Path(args.out)
    unique_values = harvest(Path(args.trace_log))
    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path} with {len(unique_values)} unique state representations")


if __name__ == "__main__":
    main()
