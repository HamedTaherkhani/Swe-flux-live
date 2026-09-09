#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/exceptions.py"
TARGET_FUNC = "lark.exceptions.UnexpectedInput.match_examples"
TARGET_CLASS = "UnexpectedInput"
TARGET_NAME = "match_examples"
PARAMETER_LINE = 75
TRACKED_VARIABLES = (
    "candidate",
    "example",
    "examples",
    "i",
    "j",
    "label",
    "malformed",
    "parse_fn",
    "self",
    "token_type_match_fallback",
    "use_accepts",
    "ut",
)

QUESTION = """Run exactly the pytest test `lark_qa/exceptions_match_examples_s4_dataflow/files/testcase.py::TestUnexpectedInputDataFlow::test_generated_error_catalog` in a fresh CPython process. Across both invocations made by that test of `lark.exceptions.UnexpectedInput.match_examples`, defined at `lark/exceptions.py:75-137`, what unique source-line def-use pairs are observed at runtime?

Track exactly these local variable names: `candidate`, `example`, `examples`, `i`, `j`, `label`, `malformed`, `parse_fn`, `self`, `token_type_match_fallback`, `use_accepts`, and `ut`. A definition is a binding of one of those plain local names. Treat every parameter binding (`self`, `parse_fn`, `examples`, `token_type_match_fallback`, and `use_accepts`) as a definition at the function's `def` line, line 75, immediately upon each call. A successful assignment to a plain local name is a definition at the 1-based physical line where that assignment begins, after all right-hand-side uses on that execution. Assignment to a subscription or attribute does not redefine its base name: for example, assigning to `mapping[key]` uses `mapping` and `key` but does not define `mapping`. A `for` target is redefined at the loop-header line once for each successful retrieval of an item, before the body executes; the final exhausted header check defines nothing. An augmented assignment such as `total += item` first uses the old reaching definition of `total` and evaluates `item`, then creates a new definition of `total` on that line. A comprehension target is likewise defined once per successfully produced item, but in that comprehension's own scope; comprehension-local evaluations do not count as evaluations in this target frame.

A use is one actual runtime evaluation, in a `match_examples` frame itself, of a syntactic `Name` load for one of the tracked variables. Count separate load occurrences on the same source line separately when determining observations. Respect short-circuit evaluation: a skipped operand produces no use. Evaluations in called functions do not count as uses in the caller's frame. A definition reaches a use when it is the most recent definition of the same local binding earlier in that invocation, with no intervening definition. One observation is one evaluated tracked-name load reached by one definition; repeated loop executions can observe the same triple repeatedly, but the output retains that triple only once.

An invocation is one runtime call of exactly `lark.exceptions.UnexpectedInput.match_examples`, numbered 1-based in chronological call order while calculating; invocation numbers are not emitted, and unique triples are aggregated across both invocations. For either `for` loop, iteration N is the Nth successful item retrieval followed by entry into that loop's body, not the final exhaustion check.

Line numbers are absolute, 1-based physical lines in `lark/exceptions.py` as it exists in the repository. For a multi-line statement or expression, use the physical line where the particular `Name` load or definition syntactically begins; an executed-line event for a statement begins on that statement or expression's corresponding physical line. The `def` line can appear only for the parameter definitions described above. Decorator and docstring lines are neither definitions nor uses.

Return exactly one JSON object with shape `{"observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]}`. Each row has exactly those three keys. `variable` is the exact source identifier as a JSON string, and `def_line` and `use_line` are positive JSON integers, with no `repr()` or `str()` conversion and no null or omitted values. Remove duplicate observations that have the same `(variable, def_line, use_line)` triple, and emit no row for an unobserved triple. Sort rows by `variable` in ascending Unicode code-point order, then by `def_line` ascending, then by `use_line` ascending."""

EVENT_RE = re.compile(
    r"\s(?P<file>\S*lark/exceptions\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_target_function(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")
    tree = ast.parse(source, filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == TARGET_NAME:
                    return child
    fail(f"cannot locate {TARGET_CLASS}.{TARGET_NAME} in {source_path}")


def static_line_facts(function_node):
    uses = {}
    definitions = {}
    for node in ast.walk(function_node):
        if isinstance(node, ast.Name) and node.id in TRACKED_VARIABLES:
            if isinstance(node.ctx, ast.Load):
                uses.setdefault(node.lineno, []).append(node.id)
            elif isinstance(node.ctx, ast.Store):
                definitions.setdefault(node.lineno, []).append(node.id)
        elif isinstance(node, ast.AugAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in TRACKED_VARIABLES
            ):
                uses.setdefault(node.target.lineno, []).append(node.target.id)
        elif (
            isinstance(node, ast.ExceptHandler)
            and isinstance(node.name, str)
            and node.name in TRACKED_VARIABLES
        ):
            definitions.setdefault(node.lineno, []).append(node.name)
    for names in uses.values():
        names.sort()
    for names in definitions.values():
        names.sort()
    return uses, definitions


class FrameState:
    def __init__(self):
        self.reaching = {
            name: PARAMETER_LINE
            for name in (
                "self",
                "parse_fn",
                "examples",
                "token_type_match_fallback",
                "use_accepts",
            )
        }
        self.pending_line = None
        self.pending_definitions = ()
        self.previous_line = None
        self.outer_iterable_evaluated = False

    def resolve_pending(self, next_line):
        if self.pending_line is None:
            return
        successful = True
        if self.pending_line == 102:
            successful = next_line == 103
        elif self.pending_line == 105:
            successful = next_line in (106, 107)
        if successful:
            for name in self.pending_definitions:
                self.reaching[name] = self.pending_line
        self.pending_line = None
        self.pending_definitions = ()


def parse_observations(trace_text, uses, definitions):
    pairs = set()
    stack = []
    target_events = 0
    target_calls = 0
    target_lines = 0

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            target_calls += 1
            stack.append(FrameState())
            continue
        if not stack:
            fail(f"encountered {event} event without an active target frame")
        frame = stack[-1]

        if event == "line":
            target_lines += 1
            frame.resolve_pending(line)
            line_uses = list(uses.get(line, ()))

            # A for-loop's iterable expression is evaluated only when its
            # iterator is created, although its header line is revisited.
            if line == 102:
                if frame.outer_iterable_evaluated:
                    line_uses = [name for name in line_uses if name != "examples"]
                frame.outer_iterable_evaluated = True
            elif line == 105 and frame.previous_line != 103:
                line_uses = [name for name in line_uses if name != "example"]

            # The generated test always gives every UnexpectedToken reaching
            # line 129 the same token type as self, so the right operand of
            # this same-line `and` is evaluated on every such execution.
            for variable in line_uses:
                if variable not in frame.reaching:
                    fail(
                        f"use of {variable} at line {line} has no reaching definition"
                    )
                pairs.add((variable, frame.reaching[variable], line))

            frame.pending_line = line
            frame.pending_definitions = tuple(definitions.get(line, ()))
            frame.previous_line = line
        elif event == "return":
            frame.resolve_pending(line)
            stack.pop()

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if target_lines == 0:
        fail(f"trace contains zero line events for {TARGET_FUNC}")
    if stack:
        fail(f"trace ended with {len(stack)} active target frame(s)")
    if not pairs:
        fail("trace produced no observed def-use pairs")
    return pairs, target_calls, target_lines


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    function_node = find_target_function(Path(TARGET_FILE))
    if function_node.lineno != 75 or function_node.end_lineno != 137:
        fail(
            "target source range changed: "
            f"expected 75-137, got {function_node.lineno}-{function_node.end_lineno}"
        )
    uses, definitions = static_line_facts(function_node)
    pairs, target_calls, target_lines = parse_observations(
        trace_text, uses, definitions
    )

    rows = [
        {
            "def_line": def_line,
            "use_line": use_line,
            "variable": variable,
        }
        for variable, def_line, use_line in sorted(pairs)
    ]
    document = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": rows},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {out_path} with {len(rows)} unique pairs from "
        f"{target_calls} calls and {target_lines} line events"
    )


if __name__ == "__main__":
    main()
