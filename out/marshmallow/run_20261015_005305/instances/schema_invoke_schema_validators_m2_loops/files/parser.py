#!/usr/bin/env python
"""Derive the M2_Loops oracle for Schema._invoke_schema_validators from a trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_QUAL = "marshmallow.schema.Schema._invoke_schema_validators"
TEST_REL = (
    "marshmallow_qa/schema_invoke_schema_validators_m2_loops/files/testcase.py"
)

LINE_RE = re.compile(r"\s(\S+):(\d+) (\S+) event=(\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loops(src_path):
    tree = ast.parse(Path(src_path).read_text(encoding="utf-8"))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Schema":
            for fn in cls.body:
                if (
                    isinstance(fn, ast.FunctionDef)
                    and fn.name == "_invoke_schema_validators"
                ):
                    outer = [n for n in fn.body if isinstance(n, ast.For)]
                    if len(outer) != 1:
                        fail("expected exactly one outer for loop")
                    outer = outer[0]
                    inner = [
                        n
                        for n in ast.walk(outer)
                        if isinstance(n, ast.For) and n is not outer
                    ]
                    if len(inner) != 1:
                        fail("expected exactly one inner for loop")
                    return outer, inner[0]
    fail("target function not found in source")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    root = Path(__file__).resolve().parents[3]
    src = root / TARGET_REL
    if not src.is_file():
        src = Path("/testbed") / TARGET_REL
    outer, inner = find_loops(src)
    inner_header = inner.lineno
    inner_body_first = inner.body[0].lineno
    stmt_span = set(range(inner.body[0].lineno, inner.body[0].end_lineno + 1))
    outer_header = outer.lineno

    calls = 0
    inner_iters = 0
    # Stack of "previous line event" per active invocation. Within one
    # iteration the multi-line call statement re-fires its first line after
    # its argument lines; count only entries from outside the statement.
    prev_stack = []
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        path, lineno, qual, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if not path.replace("\\", "/").endswith(TARGET_REL) or qual != TARGET_QUAL:
            continue
        if event == "call":
            calls += 1
            prev_stack.append(None)
        elif event == "return":
            if not prev_stack:
                fail("unbalanced return event in trace")
            prev_stack.pop()
        elif event == "line":
            if not prev_stack:
                fail("line event outside an invocation")
            if lineno == inner_body_first and prev_stack[-1] not in stmt_span:
                inner_iters += 1
            prev_stack[-1] = lineno

    if calls == 0:
        fail("trace contains zero call events for the target function")

    question = (
        f"Consider the test class `InvokeSchemaValidatorsLoopTest` in `{TEST_REL}`. "
        "Run ALL 12 test methods in that class (each pytest id has the form "
        f"`{TEST_REL}::InvokeSchemaValidatorsLoopTest::test_<name>`), in the "
        "default pytest order, as a single test run. The answer aggregates over "
        "every test method in the class.\n\n"
        f"The target is `marshmallow.schema.Schema._invoke_schema_validators` in "
        f"`{TARGET_REL}`. It contains two nested `for` loops: the OUTER loop "
        f"whose header is on line {outer_header} (`for attr_name, hook_many, "
        f"validator_kwargs in self._hooks[VALIDATES_SCHEMA]:`), and the INNER "
        f"loop whose header begins on line {inner_header} (`for idx, (item, "
        f"orig) in enumerate(`), nested inside the outer loop's `if many and not "
        f"pass_collection:` branch. Line numbers are absolute and 1-based in the "
        f"file as it exists in the repository.\n\n"
        "Count every invocation of the target during the run (an invocation = "
        "one call of the function, including calls on nested schemas created by "
        "`fields.Nested`, calls for both `pass_collection=True` and "
        "`pass_collection=False`, and calls reached via `Schema.load` or "
        "`Schema.validate`). One iteration of the INNER loop = one execution of "
        f"the inner loop body's first line (line {inner_body_first}, the start of "
        "the multi-line `self._run_validator(` call statement), i.e. one "
        "`(idx, (item, orig))` element produced by the inner loop's iterator; "
        "count it once per element no matter how many argument lines the "
        "statement spans and regardless of whether the validator raises "
        "`ValidationError` (which `_run_validator` catches). Iterations that "
        "never happen because the outer loop `continue`s, because the "
        "`else` branch is taken, or because the target is never called, "
        "contribute nothing.\n\n"
        "Report `total_iterations`: the total number of INNER-loop iterations "
        "summed over all invocations of the target across all 12 test methods, "
        "as a JSON integer (e.g. `{\"total_iterations\": 4}` would mean four "
        "body executions in total). Answer with a JSON object of exactly the "
        "shape `{\"total_iterations\": int}`."
    )

    oracle = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": inner_iters},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(f"invocations={calls}")


if __name__ == "__main__":
    main()
