#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "lark.parsers.earley.Parser._parse.<locals>.scan"
TARGET_FILE_SUFFIX = "/lark/parsers/earley.py"
OBSERVATION_LINE = 225

QUESTION = """Run every test method in the unittest class `EarleyScanProgramStateTests` from `lark_qa/earley_scan_m3_state/files/testcase.py`: `test_dense_short_rows`, `test_sparse_nested_rows`, `test_signed_number_mix`, `test_wide_expression_cycle`, `test_frequent_nested_groups`, `test_rare_signed_values`, `test_alternating_terminators`, `test_long_operator_chain`, `test_compact_nested_chain`, `test_shifted_branch_pattern`, `test_prime_seed_rows`, and `test_extended_mixed_rows`. Equivalently, the scope is all twelve pytest ids of the form `lark_qa/earley_scan_m3_state/files/testcase.py::EarleyScanProgramStateTests::<method>` for the listed methods. Aggregate observations over ALL listed methods and every invocation of the nested target function `lark.parsers.earley.Parser._parse.<locals>.scan` (the function denoted `Parser._parse.scan` in the assignment) in `lark/parsers/earley.py` during those test runs.

An invocation means one runtime call of that exact nested function, numbered 1-based in chronological order across the complete pytest run; the invocation number only defines the scope and is not included in the answer. In every invocation, observe the executed-line event immediately before absolute source line 225. This is the absolute, 1-based line number in `lark/parsers/earley.py` as it exists in the repository. An executed-line event occurs immediately before the statement or expression beginning on that line; continuation lines of a multi-line statement do not create separate observation points merely because source text appears there. The function's `def` line and docstring lines, and call, return, and exception events, are not observations.

At each observation, compute the derived five-element state tuple `scan_state = (i, len(to_scan), len(next_to_scan), len(next_set), len(node_cache))` from the current runtime objects, in exactly that order. Thus the observation includes the input scan set plus three containers created in the invocation and mutated in place while the loop executes; use their actual lengths at line 225, after the loop has finished. Take `repr()` of the whole tuple, producing a string with ordinary Python representation rules. Every tuple element is an integer, so, for example, the unrelated tuple `(2, 4)` has repr string `'(2, 4)'`. No JSON spelling substitution is performed inside repr strings; if Python-only values were present, Python spellings such as `None` and `True`, not JSON `null` and `true`, would be used.

Remove duplicate repr strings across every invocation and all twelve methods. Sort the remaining strings in ascending Python string order: lexicographically by Unicode code point with normal prefix ordering; there is no secondary tie-breaker because duplicates are removed. Return exactly `{"unique_values": [...]}`, where `unique_values` is the sorted JSON array of those strings. No missing observation is represented by an empty string or JSON null; every successful invocation contributes its line-225 state."""

LINE_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception).* locals=(?P<locals>\{.*\})$"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_changed_locals(text, trace_line):
    try:
        changed = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals on trace line {trace_line}: {exc}")
    if not isinstance(changed, dict):
        fail(f"locals are not a dictionary on trace line {trace_line}")
    return changed


def parse_int_repr(value, name, trace_line):
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse {name} on trace line {trace_line}: {exc}")
    if not isinstance(parsed, int) or isinstance(parsed, bool):
        fail(f"{name} is not represented by an integer on trace line {trace_line}")
    return parsed


def parse_trace(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = None
    values = set()
    observation_count = 0

    with trace_path.open("r", encoding="utf-8") as handle:
        for trace_line, raw_line in enumerate(handle, 1):
            match = LINE_RE.search(raw_line.rstrip("\n"))
            if not match:
                continue
            if match.group("func") != TARGET_FUNC:
                continue
            if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
                continue

            target_events += 1
            event = match.group("event")
            changed = parse_changed_locals(match.group("locals"), trace_line)

            if event == "call":
                if invocation is not None:
                    fail(f"nested target invocation begins on trace line {trace_line}")
                if "i" not in changed:
                    fail(f"call event lacks local i on trace line {trace_line}")
                invocation = {
                    "i": parse_int_repr(changed["i"], "i", trace_line),
                    "iterations": 0,
                    "next_to_scan_adds": 0,
                    "next_set_adds": 0,
                    "labels": set(),
                    "observed": False,
                    "state": dict(changed),
                }
                continue

            if invocation is None:
                fail(f"target {event} event appeared outside an invocation on trace line {trace_line}")
            invocation["state"].update(changed)

            if event == "line":
                source_line = int(match.group("line"))
                if source_line == 203:
                    invocation["iterations"] += 1
                elif source_line == 216:
                    label = invocation["state"].get("label")
                    if label is None:
                        fail(f"line 216 lacks current label on trace line {trace_line}")
                    invocation["labels"].add(label)
                elif source_line == 220:
                    invocation["next_to_scan_adds"] += 1
                elif source_line == 223:
                    invocation["next_set_adds"] += 1
                elif source_line == OBSERVATION_LINE:
                    if invocation["observed"]:
                        fail(f"duplicate line-225 observation in one invocation on trace line {trace_line}")
                    matched = (
                        invocation["next_to_scan_adds"] + invocation["next_set_adds"]
                    )
                    if matched < len(invocation["labels"]):
                        fail(f"inconsistent node-cache accounting on trace line {trace_line}")
                    state_tuple = (
                        invocation["i"],
                        invocation["iterations"],
                        invocation["next_to_scan_adds"],
                        invocation["next_set_adds"],
                        len(invocation["labels"]),
                    )
                    values.add(repr(state_tuple))
                    invocation["observed"] = True
                    observation_count += 1

            if event == "return":
                if not invocation["observed"]:
                    fail(f"target invocation returned without line-225 observation on trace line {trace_line}")
                invocation = None
            elif event == "exception":
                fail(f"unexpected exception event in target on trace line {trace_line}")

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation is not None:
        fail("trace ended during a target invocation")
    if observation_count == 0:
        fail(f"trace contains no line-{OBSERVATION_LINE} observations")
    if len(values) < 8:
        fail(f"only {len(values)} distinct state values were observed; expected at least 8")
    return sorted(values)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

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
