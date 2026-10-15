#!/usr/bin/env python
"""Parse the call trace of fields.py into per-method invocation counts for the
methods defined in the bodies of classes `Number` and `Decimal`."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/marshmallow/fields.py"
MODULE = "marshmallow.fields"
SCOPE_CLASSES = ("Number", "Decimal")
TARGET_QUAL = "marshmallow.fields.Decimal._validated"
TEST_PATH = "marshmallow_qa/fields_validated_m6_calls/files/testcase.py"
TEST_CLASS = "TestDecimalValidated"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(src_path):
    """Every def statement directly in the body of class Number or Decimal."""
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    quals = []
    found = set()
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name in SCOPE_CLASSES):
            continue
        found.add(node.name)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                quals.append(f"{MODULE}.{node.name}.{item.name}")
    if found != set(SCOPE_CLASSES):
        fail(f"scope classes missing in {src_path}: {set(SCOPE_CLASSES) - found}")
    if len(set(quals)) != len(quals):
        fail("duplicate qualnames in scope")
    if TARGET_QUAL not in quals:
        fail(f"{TARGET_QUAL} not found in {src_path}")
    return sorted(quals)


def build_question():
    return (
        f"In this repository, the test file `{TEST_PATH}` defines the unittest class "
        f"`{TEST_CLASS}` with twelve test methods (`test_01_...` through `test_12_...`). "
        f"Run ALL test methods of this class with pytest (pytest id "
        f"`{TEST_PATH}::{TEST_CLASS}`). The tests build `marshmallow.fields.Decimal` "
        f"fields (and a few other number fields) from seeded random generators and call "
        f"the target `{TARGET_QUAL}` (the `_validated` method of class `Decimal` in "
        f"`{TARGET_REL}`) directly, plus some `serialize`/`deserialize` calls.\n\n"
        f"Scope: consider every function whose `def` statement appears directly in the "
        f"body of class `Number` or directly in the body of class `Decimal` in "
        f"`{TARGET_REL}` (the two module-level classes with those names). This includes "
        f"`__init__`, dunder methods, underscore-prefixed methods, and decorated defs such "
        f"as properties/abstract properties (a property getter counts as a function of "
        f"the class whose body contains its `def`). Each such def is one entry; you must "
        f"find them yourself by reading the file. Methods inherited from other classes "
        f"(e.g. anything defined only in `Field`, such as `make_error`, `serialize` or "
        f"`deserialize`) are NOT entries, and methods of other subclasses of `Number` "
        f"(e.g. those defined in `Integer` or `Float`) are NOT entries. Nested functions, "
        f"lambdas and comprehensions are not entries. Code inside docstrings is not a "
        f"definition. When an instance of any class (e.g. a `Decimal`, `Integer` or "
        f"`Float` field) executes a method, the invocation is credited to the class whose "
        f"body contains the executed `def`; e.g. a `super().__init__(...)` call from "
        f"`Integer.__init__` that lands in `Number.__init__` counts for "
        f"`Number.__init__`.\n\n"
        f"Identity: `func` is the dotted name `<module>.<ClassName>.<method>` where the "
        f"module is the import name `{MODULE}` (not `src.marshmallow.fields`); for "
        f"example, the method `_bind_to_schema` of class `Tuple` would be written "
        f"`marshmallow.fields.Tuple._bind_to_schema`. `file` is the repo-relative path "
        f"`{TARGET_REL}` for every entry.\n\n"
        f"Counting: one invocation = one Python function call of that def's code (one "
        f"`'call'` event for a new frame of it, as seen by `sys.settrace`), regardless of "
        f"who calls it: calls made directly by the test, via `super()`, via "
        f"`Field.serialize`/`Field.deserialize`, from field constructors, or from any "
        f"other frame all count; a call that ends by raising an exception still counts "
        f"as one invocation. Only calls made while the test methods run count (module "
        f"import does not call any of these). None of the in-scope functions are "
        f"generators or coroutines, so there are no resumptions to consider. Counts are "
        f"summed over ALL twelve test methods of the class (not reported per test). "
        f"Functions in scope that never run in any test MUST still be listed with "
        f"`count` 0.\n\n"
        f"Answer format: a JSON object with the single key `invocation_counts`, whose "
        f"value is a list with exactly one object per in-scope function, each of the "
        f"form `{{\"count\": <int>, \"file\": <str>, \"func\": <str>}}`. Sort the list by "
        f"`func` ascending using plain Python string comparison (Unicode code point "
        f"order, so uppercase letters sort before `_`, which sorts before lowercase "
        f"letters). `func` values are unique, so no tie-break is needed."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {trace_path}")

    repo_root = Path(__file__).resolve().parents[3]
    src_path = repo_root / TARGET_REL
    if not src_path.is_file():
        src_path = Path("/testbed") / TARGET_REL
    scope = scope_functions(src_path)
    scope_set = set(scope)

    counts = Counter()
    n_events = 0
    for line in text.splitlines():
        m = EVENT_RE.search(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_REL):
            continue
        func = m.group("func")
        if func not in scope_set:
            continue
        n_events += 1
        if m.group("event") == "call":
            counts[func] += 1

    if n_events == 0 or counts[TARGET_QUAL] == 0:
        fail(f"no call events for {TARGET_QUAL} in {trace_path}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": TARGET_REL, "func": f} for f in scope
        ]
    }
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
