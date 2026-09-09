#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "lark.lexer.BasicLexer.next_token"
TARGET_FILE_SUFFIX = "/lark/lexer.py"
OBSERVATION_LINES = {695, 701}

TEST_METHODS = [
    "test_alternating_assignment_forms",
    "test_compact_seeded_program",
    "test_dense_comments_and_nested_atoms",
    "test_extended_seeded_program",
    "test_long_rows_rare_comments",
    "test_many_parenthesized_atoms",
    "test_numeric_heavy_mixture",
    "test_operator_phase_shift",
    "test_separator_phase_shift",
    "test_short_rows_frequent_comments",
    "test_sparse_comments_with_long_rows",
    "test_string_heavy_mixture",
]

QUESTION = """Run every test method in the unittest class `LexerProgramStateTests` from `lark_qa/lexer_next_token_m3_state/files/testcase.py`: `test_alternating_assignment_forms`, `test_compact_seeded_program`, `test_dense_comments_and_nested_atoms`, `test_extended_seeded_program`, `test_long_rows_rare_comments`, `test_many_parenthesized_atoms`, `test_numeric_heavy_mixture`, `test_operator_phase_shift`, `test_separator_phase_shift`, `test_short_rows_frequent_comments`, `test_sparse_comments_with_long_rows`, and `test_string_heavy_mixture`. Equivalently, the scope is all pytest ids having the form `lark_qa/lexer_next_token_m3_state/files/testcase.py::LexerProgramStateTests::<method>` for those twelve methods. Aggregate observations over ALL of those methods and over every invocation of `lark.lexer.BasicLexer.next_token` in `lark/lexer.py` during their runs.

An invocation means one runtime call of that exact function, numbered 1-based in chronological order within the complete run; numbering is only a scope definition and is not included in the answer. At each executed-line event immediately before absolute source line 695 and immediately before absolute source line 701, inspect the current locals of that invocation. These are absolute, 1-based line numbers in `lark/lexer.py` as it exists in the repository. An executed-line event occurs immediately before the statement or expression beginning on that line; continuation lines of a multi-line statement do not count as separate observation points merely because text appears there. The function's `def` line, decorators, call events, return events, and exception events are not observations.

Keep an observation only when the current local `ignored` is exactly the boolean `True` and all five locals `res`, `ignored`, `type_`, `value`, and `t` are defined. For each retained observation, construct the five-element Python tuple `(res, ignored, type_, value, t)` from the current runtime objects in exactly that order, then take `repr()` of the whole tuple. This intentionally combines the scanner-result container with the branch flag, token type/value, and the mutable token-or-`None` state at two different program points. Use ordinary Python `repr`, including Python spellings such as `True` and `None` inside the string; for example, `repr(("xy", False))` is the string `('xy', False)`. No JSON `null`/`true` substitution is performed inside these strings.

Remove duplicate repr strings across both observation lines, every invocation, and all twelve methods. Sort the remaining strings in ascending Python string order (lexicographic by Unicode code point, with normal prefix ordering and no secondary tie-breaker because duplicates were removed). Return exactly `{"unique_values": [...]}`, where `unique_values` is that sorted JSON array of strings."""


LINE_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception).* locals=(?P<locals>\{.*\})$"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_trace(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    state = None
    target_events = 0
    observed_lines = set()
    values = set()

    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            match = LINE_RE.search(raw_line.rstrip("\n"))
            if not match:
                continue
            if match.group("func") != TARGET_FUNC:
                continue
            if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
                continue

            target_events += 1
            event = match.group("event")
            try:
                changed = ast.literal_eval(match.group("locals"))
            except (SyntaxError, ValueError) as exc:
                fail(f"cannot parse locals on trace line {line_number}: {exc}")
            if not isinstance(changed, dict):
                fail(f"locals are not a dictionary on trace line {line_number}")

            if event == "call":
                state = dict(changed)
                continue
            if state is None:
                fail(f"target {event} event appeared outside an invocation on trace line {line_number}")
            state.update(changed)

            if event == "line":
                source_line = int(match.group("line"))
                if source_line in OBSERVATION_LINES:
                    observed_lines.add(source_line)
                    required = ("res", "ignored", "type_", "value", "t")
                    if all(name in state for name in required) and state["ignored"] == "True":
                        values.add(
                            f"({state['res']}, {state['ignored']}, {state['type_']}, "
                            f"{state['value']}, {state['t']})"
                        )

            if event == "return":
                state = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if observed_lines != OBSERVATION_LINES:
        fail(f"missing observation lines; saw {sorted(observed_lines)}, expected {sorted(OBSERVATION_LINES)}")
    if len(values) < 8:
        fail(f"only {len(values)} distinct state values were observed; expected at least 8")
    return sorted(values)


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True, type=Path)
    arg_parser.add_argument("--out", required=True, type=Path)
    args = arg_parser.parse_args()

    unique_values = parse_trace(args.trace_log)
    document = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {args.out} with {len(unique_values)} unique values")


if __name__ == "__main__":
    main()
