#!/usr/bin/env python
"""Parse the call trace of the serialize hooks in fields.py into per-method
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
METHOD_NAMES = ("serialize", "_serialize", "get_value")
TARGET_QUAL = "marshmallow.fields.Field.serialize"
TEST_PATH = "marshmallow_qa/fields_serialize_m6_calls/files/testcase.py"
TEST_CLASS = "TestDirectFieldSerialize"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(src_path):
    """Every `serialize`/`_serialize`/`get_value` def directly in a top-level class body."""
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
        f"`{TEST_PATH}::{TEST_CLASS}`). Each test builds field instances and calls the "
        f"target `{TARGET_QUAL}` (i.e. `Field.serialize` in `{TARGET_REL}`) directly; "
        f"some of those calls fan out further (container fields delegating to their "
        f"inner fields, nested schemas dumping their own fields, `super()` chains).\n\n"
        f"Scope: consider every method in `{TARGET_REL}` whose name is exactly "
        f"`serialize`, exactly `_serialize`, or exactly `get_value`, and whose `def` "
        f"statement appears directly in the body of a module-level class of that file - "
        f"i.e. the methods of `Field` with those names plus EVERY class in the file that "
        f"defines (overrides) one of them in its own body. You must find these classes "
        f"yourself by reading the file. Each such (class, method name) pair is one "
        f"function in scope. Code that only appears inside docstrings is not a definition. "
        f"Inherited methods do NOT get their own entry: a class that does not define the "
        f"method itself is not in scope for it, and when an instance of such a class runs "
        f"an inherited method, the invocation is credited to the class whose body "
        f"contains the executed `def`. Nested functions, lambdas, comprehensions and "
        f"generator expressions created inside these methods are not entries and are not "
        f"counted. No other methods (e.g. `deserialize`, `_deserialize`, `__init__`, "
        f"`_to_string`, `_format_num`, properties) and no functions from other files "
        f"(e.g. `Schema._serialize` in `src/marshmallow/schema.py` or the module-level "
        f"`get_value` in `src/marshmallow/utils.py`) are in scope.\n\n"
        f"Identity: `func` is the dotted name `<module>.<ClassName>.<method>` where the "
        f"module is the import name `{MODULE}` (not `src.marshmallow.fields`); "
        f"for example, the method `_bind_to_schema` of class `Tuple` would be written "
        f"`marshmallow.fields.Tuple._bind_to_schema`. `file` is the repo-relative path "
        f"`{TARGET_REL}` for every entry.\n\n"
        f"Counting: one invocation = one Python function call of that method's code "
        f"(one `'call'` event for a new frame of it, as seen by `sys.settrace`), "
        f"regardless of who calls it: calls made directly by the test, by `Field.serialize` "
        f"itself, by other fields (e.g. container fields calling an inner field's "
        f"`_serialize`), via `super()`, recursively, or by schemas dumping nested data all "
        f"count. Only calls made while the test methods run count (field/schema "
        f"construction at import time cannot call these methods anyway). None of the "
        f"in-scope methods are generators or coroutines, so there are no resumptions to "
        f"consider. Counts are summed over ALL twelve test methods of the class (not "
        f"reported per test). Functions in scope that never run in any test MUST still "
        f"be listed with `count` 0.\n\n"
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
