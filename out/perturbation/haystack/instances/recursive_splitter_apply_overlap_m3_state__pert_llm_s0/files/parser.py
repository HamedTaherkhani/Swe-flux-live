from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


TARGET_FUNCTION = "haystack.components.preprocessors.recursive_splitter._apply_overlap"

QUESTION = """Run the complete unittest class `TestRecursiveSplitterOverlapState` in
`haystack_qa/recursive_splitter_apply_overlap_m3_state/files/testcase.py` using the pytest
selection
`haystack_qa/recursive_splitter_apply_overlap_m3_state/files/testcase.py::TestRecursiveSplitterOverlapState`.
The run therefore covers all twelve methods: `test_01_char_alternating_markers`,
`test_02_char_recursive_markers`, `test_03_char_dense_boundaries`,
`test_04_char_large_overlap`, `test_05_char_newline_hierarchy`,
`test_06_char_sparse_primary`, `test_07_word_pipe_groups`,
`test_08_word_recursive_groups`, `test_09_word_newline_groups`,
`test_10_word_high_overlap`, `test_11_word_double_colon`, and
`test_12_word_mixed_boundaries`. Aggregate the observations from every method, in the order
in which pytest executes that class.

For every invocation of
`haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._apply_overlap`
in `haystack/components/preprocessors/recursive_splitter.py`, observe the local variable
`overlapped_chunks` at that invocation's normal function-return event on absolute, 1-based
source line 226. An invocation means one call of this function during the selected run;
invocations are numbered 1-based in chronological call order, although invocation numbers
are not included in the answer. A normal function-return event occurs after the return
expression has been evaluated and immediately before that frame is destroyed; exception
events and frames of every other function are excluded. For a multi-line statement, an
executed-line event belongs to the absolute line on which its statement or expression begins;
decorator, `def`, and docstring lines are not observation points here.

For each observation, apply Python's built-in `repr()` to the whole `overlapped_chunks` list,
including Python spellings inside the resulting string (for example, `None` rather than JSON
`null`). Treat each resulting representation as one string. Remove duplicate strings across
all invocations, then sort the distinct strings in ascending lexicographic order by Unicode
code point, exactly as Python's default ordering of `str` values does.

Return exactly one JSON object with the key `unique_values`. Its value must be the sorted JSON
array of those Python-repr strings; there are no additional keys, and no observation is
represented by an empty string, JSON `null`, or an omitted array element."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the deterministic program-state oracle.")
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def extract_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    return_events = 0
    values: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = f" {TARGET_FUNCTION} event="
        if marker not in line:
            continue
        target_events += 1

        event_text = line.split(marker, 1)[1]
        if not event_text.startswith("return "):
            continue
        return_events += 1

        if " locals=" not in event_text:
            raise RuntimeError(f"target return event lacks locals on trace line {line_number}")
        locals_text = event_text.split(" locals=", 1)[1]
        try:
            local_values = ast.literal_eval(locals_text)
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse locals on trace line {line_number}: {exc}") from exc

        representation = local_values.get("overlapped_chunks")
        if not isinstance(representation, str):
            raise RuntimeError(f"target return lacks overlapped_chunks on trace line {line_number}")
        if representation.endswith("..."):
            raise RuntimeError(f"overlapped_chunks was truncated on trace line {line_number}")
        try:
            represented_value = ast.literal_eval(representation)
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"invalid overlapped_chunks repr on trace line {line_number}: {exc}") from exc
        if not isinstance(represented_value, list) or repr(represented_value) != representation:
            raise RuntimeError(f"non-canonical list repr on trace line {line_number}")
        values.add(representation)

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNCTION}")
    if return_events == 0:
        raise RuntimeError(f"trace contains no normal returns for {TARGET_FUNCTION}")
    if not values:
        raise RuntimeError("trace produced no overlapped_chunks observations")
    return sorted(values)


def main() -> None:
    args = parse_args()
    unique_values = extract_unique_values(args.trace_log)
    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
