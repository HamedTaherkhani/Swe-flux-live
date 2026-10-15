#!/usr/bin/env python
"""Parse the trace log into per-function invocation counts (M6_InterProceduralCFG)."""

import argparse
import ast
import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
FIELDS_FILE = "src/marshmallow/fields.py"
UTILS_FILE = "src/marshmallow/utils.py"
FIELDS_MOD = "marshmallow.fields"
UTILS_MOD = "marshmallow.utils"
SCOPE_CLASSES = ("_TemporalField", "DateTime", "NaiveDateTime", "AwareDateTime")
TARGET = "marshmallow.fields.AwareDateTime._deserialize"
TEST_FILE = "marshmallow_qa/fields_deserialize_m6_calls_4/files/testcase.py"
TEST_CLASS = "TestAwareDateTimeDeserialize"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_tree(rel):
    path = os.path.join(REPO_ROOT, rel)
    if not os.path.isfile(path):
        die(f"source file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def build_scope():
    scope = {}
    for node in load_tree(UTILS_FILE).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope[f"{UTILS_MOD}.{node.name}"] = UTILS_FILE
    found = set()
    for node in load_tree(FIELDS_FILE).body:
        if isinstance(node, ast.ClassDef) and node.name in SCOPE_CLASSES:
            found.add(node.name)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope[f"{FIELDS_MOD}.{node.name}.{item.name}"] = FIELDS_FILE
    missing = set(SCOPE_CLASSES) - found
    if missing:
        die(f"classes not found in {FIELDS_FILE}: {sorted(missing)}")
    return scope


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        die(f"trace log empty: {args.trace_log}")

    scope = build_scope()
    counts = {name: 0 for name in scope}
    events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            events += 1
            if m.group("event") != "call":
                continue
            func = m.group("func")
            if func not in scope:
                continue
            if not m.group("file").replace("\\", "/").endswith(scope[func]):
                continue
            counts[func] += 1

    if events == 0:
        die("trace log contains no events")
    if counts.get(TARGET, 0) == 0:
        die(f"no call events for target {TARGET}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": scope[f], "func": f} for f in sorted(scope)
        ]
    }

    question = (
        f"In this repository, the test file `{TEST_FILE}` defines the unittest class "
        f"`{TEST_CLASS}` with twelve test methods (`test_01_...` through `test_12_...`). "
        f"Run ALL test methods of this class with pytest (pytest id `{TEST_FILE}::{TEST_CLASS}`). "
        "Each test calls the target method `marshmallow.fields.AwareDateTime._deserialize` "
        f"(class `AwareDateTime` in `{FIELDS_FILE}`) directly on freshly built field instances.\n\n"
        "Scope: the tracked functions are (a) EVERY module-level function defined in "
        f"`{UTILS_FILE}` (every top-level `def` of that file, including those whose name starts "
        "with an underscore), and (b) EVERY method whose `def` statement appears directly in the "
        f"class body of one of these four classes in `{FIELDS_FILE}`: `_TemporalField`, `DateTime`, "
        "`NaiveDateTime`, `AwareDateTime` (this includes `__init__`, static methods and abstract "
        "methods defined there, regardless of whether they are ever called). You must find the members "
        "yourself by reading those files. Inherited methods do NOT get their own entry: a method inherited "
        "from another class (e.g. from `Field`) is out of scope unless its `def` sits in one of the four "
        "class bodies, and when an instance runs an inherited in-scope method, the call is credited to the "
        "class whose body contains the executed `def` (e.g. `super().__init__` reaching "
        "`_TemporalField.__init__` counts for `_TemporalField.__init__`). Nothing else is in scope: no "
        "methods of other classes in `fields.py` (e.g. `Field.make_error`, `Field.__init__`), no functions "
        "from other files (schema, exceptions, the standard library, or the test file itself, including its "
        "helper functions and its `tzinfo` subclass), and no lambdas, comprehensions, or nested functions.\n\n"
        "Identity: `func` is the dotted name `<module>.<qualname>` using the import names "
        "`marshmallow.utils` and `marshmallow.fields` (not `src.marshmallow...`); for example the "
        "`_serialize` method of class `Date` would be written `marshmallow.fields.Date._serialize`, and a "
        "module-level utils function `foo` would be `marshmallow.utils.foo`. `file` is the repo-relative path "
        f"of the file containing the `def`: `{UTILS_FILE}` or `{FIELDS_FILE}`.\n\n"
        "Counting: one invocation = one Python function call of that function's code (one `'call'` event "
        "for a new frame of it, as seen by `sys.settrace`), from ANY caller and at any depth - calls made "
        "directly by the test body, transitively through other functions (including through `super()`, "
        "through functions looked up in class-level dictionaries, through field constructors, through "
        "schema construction, and through another in-scope function) all count. Calls that end by raising "
        "an exception still count. None of the in-scope functions are generators or coroutines, so there are "
        "no resumptions. Only what happens while the test methods themselves run is counted (test collection "
        "and module import are excluded; there are no `setUp`/`tearDown` methods). Counts are summed over ALL "
        "twelve test methods (not reported per test). Every in-scope function that never runs MUST still be "
        "listed, with `count` 0.\n\n"
        "Answer format: a JSON object with the single key `invocation_counts`, whose value is a list with "
        "exactly one object per in-scope function, each of the form "
        "`{\"count\": <int>, \"file\": <str>, \"func\": <str>}`. Sort the list by `func` ascending using plain "
        "Python string comparison (Unicode code point order, so uppercase letters sort before `_`, which sorts "
        "before lowercase letters). `func` values are unique, so no tie-break is needed."
    )

    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": question,
        "template_answer": {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
