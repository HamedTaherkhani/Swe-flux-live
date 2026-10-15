#!/usr/bin/env python
"""Per-invocation combined loop iterations of Schema._init_fields -> max/min."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_CLASS = "Schema"
TARGET_NAME = "_init_fields"
TARGET_QUAL = "marshmallow.schema.Schema._init_fields"
TEST_PATH = "marshmallow_qa/schema_init_fields_m2_loops/files/testcase.py"
TEST_CLASS = "TestInitFieldsLoops"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_function(src_path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_NAME:
                    return item
    fail(f"could not locate {TARGET_CLASS}.{TARGET_NAME} in {src_path}")


def find_loops(func):
    loops = [n for n in ast.walk(func) if isinstance(n, (ast.For, ast.While))]
    loops.sort(key=lambda n: n.lineno)
    if len(loops) != 2:
        fail(f"expected exactly 2 loop statements in target, found {len(loops)}")
    return [(n.lineno, n.body[0].lineno) for n in loops]


def build_question(def_line, last, loops):
    (h1, b1), (h2, b2) = loops
    return (
        f"In the repository, the test file `{TEST_PATH}` defines the unittest class "
        f"`{TEST_CLASS}` with twelve test methods (`test_01_...` through `test_12_...`). "
        f"Run ALL test methods of this class with pytest (pytest id "
        f"`{TEST_PATH}::{TEST_CLASS}`), in pytest's default (definition) order; the answer "
        f"aggregates over all twelve methods together.\n\n"
        f"Target function: `{TARGET_QUAL}` (i.e. `Schema._init_fields`), defined in "
        f"`{TARGET_REL}` with its `def` statement at line {def_line} (the function spans "
        f"lines {def_line}-{last}). The function contains exactly two `for` loops:\n"
        f"- loop A: the `for field_name in field_names:` statement at line {h1}, whose "
        f"body's first line is line {b1};\n"
        f"- loop B: the `for field_name, field_obj in fields_dict.items():` statement at "
        f"line {h2}, whose body's first line is line {b2}.\n"
        f"(The list/set comprehensions in the function are NOT loops for this question.)\n\n"
        f"Definitions:\n"
        f"- An invocation is one call of `Schema._init_fields` on any schema instance "
        f"during the test run, counted in chronological order across all twelve test "
        f"methods. This includes the calls made implicitly by `Schema.__init__` when a "
        f"schema is instantiated, calls made by `fields.Nested.schema` when the nested "
        f"schema is first resolved, and the explicit calls written in the tests. "
        f"Invocations that end by raising an exception still count.\n"
        f"- An iteration of a loop is one execution of that loop body's first line "
        f"(line {b1} for loop A, line {b2} for loop B); counting is 1-based, so a loop whose "
        f"body never runs (or that is never reached because an exception was raised "
        f"earlier) contributes 0 iterations. If an exception escapes from inside the body "
        f"of loop A, the iteration in which it is raised still counts (its first line did "
        f"execute) and loop B contributes 0.\n"
        f"- For each invocation, its combined iteration count is (iterations of loop A in "
        f"that invocation) + (iterations of loop B in that invocation).\n\n"
        f"Question: across ALL invocations in the whole run, what are the maximum and the "
        f"minimum per-invocation combined iteration counts?\n\n"
        f"Answer as a JSON object with exactly two keys: `max_iterations` (int, the largest "
        f"combined count over all invocations) and `min_iterations` (int, the smallest "
        f"combined count over all invocations, which may be 0). Both are plain JSON "
        f"integers (e.g. {{\"max_iterations\": 123, \"min_iterations\": 45}} would be the "
        f"format)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file():
        fail(f"trace log missing: {trace}")
    text = trace.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {trace}")

    src = Path(__file__).resolve()
    root = None
    for cand in [Path.cwd()] + list(src.parents):
        if (cand / TARGET_REL).is_file():
            root = cand
            break
    if root is None:
        fail(f"cannot locate {TARGET_REL}")
    func = find_function(root / TARGET_REL)
    loops = find_loops(func)
    body_a, body_b = loops[0][1], loops[1][1]

    invocations = []
    current = None
    n_events = 0
    for raw in text.splitlines():
        m = EVENT_RE.search(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_REL) or m.group("func") != TARGET_QUAL:
            continue
        n_events += 1
        ev, line = m.group("event"), int(m.group("line"))
        if ev == "call":
            if current is not None:
                fail("re-entrant invocation of target not supported")
            current = [0, 0]
        elif current is None:
            fail(f"event outside invocation at line {line}")
        elif ev == "line":
            if line == body_a:
                current[0] += 1
            elif line == body_b:
                current[1] += 1
        elif ev == "return":
            invocations.append(current[0] + current[1])
            current = None
    if n_events == 0:
        fail("zero events for target function in trace")
    if current is not None:
        fail("trace ended inside an invocation")
    if not invocations:
        fail("no complete invocations found")

    answer = {"max_iterations": max(invocations), "min_iterations": min(invocations)}
    oracle = {
        "question_kind": "M2_Loops",
        "question": build_question(func.lineno, func.end_lineno, loops),
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": answer,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} counts={invocations}")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
