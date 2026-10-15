#!/usr/bin/env python
"""Trace -> oracle.json for schema_invoke_field_validators_s2_loops (S2_Loops)."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_QUAL = "Schema._invoke_field_validators"
TEST_PATH = "marshmallow_qa/schema_invoke_field_validators_s2_loops/files/testcase.py"
TEST_CLASS = "InvokeFieldValidatorsLoopTest"
TEST_METHOD = "test_load_many_with_exclusions"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(source_path):
    """Return (header_line, body_first_line) of the `for ... in enumerate(data)` loop."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Schema":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "_invoke_field_validators":
                    for node in ast.walk(fn):
                        if (
                            isinstance(node, ast.For)
                            and isinstance(node.iter, ast.Call)
                            and isinstance(node.iter.func, ast.Name)
                            and node.iter.func.id == "enumerate"
                        ):
                            return node.lineno, node.body[0].lineno
    fail("could not locate the enumerate loop in the target function")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path(__file__).resolve().parents[3] / TARGET_REL
    if not src.is_file():
        src = Path.cwd() / TARGET_REL
    header, body_first = find_loop(src)

    invocations = []  # list of per-invocation body-line counts
    depth = 0
    target_events = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_REL):
            continue
        if not m.group("func").endswith("." + TARGET_QUAL):
            continue
        target_events += 1
        ev = m.group("event")
        ln = int(m.group("line"))
        if ev == "call":
            if depth == 0:
                invocations.append(0)
            depth += 1
        elif ev == "return":
            depth -= 1
        elif ev == "line" and depth == 1 and ln == body_first:
            invocations[-1] += 1

    if target_events == 0 or not invocations:
        fail("no events for the target function in the trace")
    if len(invocations) != 1:
        fail(f"expected exactly 1 invocation, got {len(invocations)}")

    question = (
        f"Run the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (class `{TEST_CLASS}`, "
        f"the file's only test method). During this test, the method "
        f"`marshmallow.schema.Schema._invoke_field_validators` defined in `{TARGET_REL}` is called "
        f"exactly once (invocation 1 = the first and only call, counting calls in chronological "
        f"order, 1-based). Consider the inner `for` loop whose header is at line {header} of "
        f"`{TARGET_REL}` (the loop over `enumerate(data)` inside the `if many:` branch; line numbers "
        f"are absolute and 1-based in the file as it exists in the repository). Note that this loop "
        f"may be entered several times within that single invocation (once per validator/field "
        f"pair that reaches it). Define one iteration as one execution of the loop body's first "
        f"line (line {body_first}, the `try:` statement). How many iterations of this loop occur in "
        f"total during invocation 1, summed over every entry into the loop within that invocation? "
        f"Iterations in which the subsequent lookup raises `KeyError` (and the item is skipped) "
        f"still count. Answer as JSON of the form {{\"loop_iteration_count\": <int>}}, where the "
        f"value is a plain JSON integer (e.g. {{\"loop_iteration_count\": 7}})."
    )
    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": invocations[0]},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
