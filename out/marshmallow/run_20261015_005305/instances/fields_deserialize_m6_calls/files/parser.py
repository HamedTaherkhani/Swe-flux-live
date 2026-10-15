#!/usr/bin/env python
"""Parse the call trace of the (de)serialize hooks in fields.py into per-method
invocation counts."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/marshmallow/fields.py"
MODULE = "marshmallow.fields"
METHOD_NAMES = ("deserialize", "_deserialize")
TARGET_QUAL = "marshmallow.fields.Field.deserialize"
TEST_PATH = "marshmallow_qa/fields_deserialize_m6_calls/files/testcase.py"
TEST_CLASS = "TestIndirectDeserialize"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(src_path):
    """Every `deserialize`/`_deserialize` def directly in a top-level class body."""
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    quals = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                item.name in METHOD_NAMES
            ):
                quals.add(f"{MODULE}.{node.name}.{item.name}")
    if TARGET_QUAL not in quals:
        fail(f"{TARGET_QUAL} not found in {src_path}")
    return sorted(quals)


def build_question():
    return (
        f"In this repository, the test file `{TEST_PATH}` defines the unittest class "
        f"`{TEST_CLASS}` with twelve test methods (`test_01_...` through `test_12_...`). "
        f"Run ALL test methods of this class with pytest (pytest id "
        f"`{TEST_PATH}::{TEST_CLASS}`). The tests never call the target directly: they "
        f"only call `Schema.load`, and the target `{TARGET_QUAL}` (i.e. "
        f"`Field.deserialize` in `{TARGET_REL}`) is reached from the schema machinery "
        f"and from container/composite fields that deserialize their inner fields.\n\n"
        f"Scope: consider every method in `{TARGET_REL}` whose name is exactly "
        f"`deserialize` or exactly `_deserialize` and whose `def` statement appears "
        f"directly in the body of a module-level class of that file - i.e. "
        f"`Field.deserialize` together with the base `_deserialize` hook and EVERY "
        f"class in the file that defines (overrides) its own `_deserialize`. You must "
        f"find these classes yourself by reading the file. Each such (class, method "
        f"name) pair is one function in scope; the `@typing.overload` stub definitions "
        f"of `deserialize` do not create extra entries (there is a single entry for "
        f"`Field.deserialize`). Inherited methods do NOT get their own entry: a class "
        f"that does not define `_deserialize` itself is not in scope, and when an "
        f"instance of such a class runs an inherited `_deserialize`, the invocation is "
        f"credited to the class whose body contains the executed `def`. No other "
        f"methods (e.g. `_serialize`, `_validated`, `_load`, `__init__`, properties) "
        f"and no functions from other files (e.g. `Schema._deserialize` in "
        f"`src/marshmallow/schema.py`) are in scope.\n\n"
        f"Identity: `func` is the dotted name `<module>.<ClassName>.<method>` where the "
        f"module is the import name `{MODULE}` (not `src.marshmallow.fields`); "
        f"for example, the method `_load` of class `Nested` would be written "
        f"`marshmallow.fields.Nested._load`. `file` is the repo-relative path "
        f"`{TARGET_REL}` for every entry.\n\n"
        f"Counting: one invocation = one Python function call of that method's code "
        f"(one `'call'` event for a new frame of it, as seen by `sys.settrace`), "
        f"regardless of who calls it: calls made by the schema, by other fields "
        f"(e.g. `List`, `Tuple`, `Dict`, `Nested`, `Enum`), via `super()`, recursively, "
        f"or by nested schemas all count. Calls that end by raising an exception still "
        f"count. None of the in-scope methods are generators or coroutines, so there "
        f"are no resumptions to consider. Counts are summed over ALL twelve test "
        f"methods of the class (not reported per test). Functions in scope that never "
        f"run in any test MUST still be listed with `count` 0.\n\n"
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
