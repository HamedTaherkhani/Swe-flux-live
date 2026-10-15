"""Parse the trace log into per-function invocation counts (M6_InterProceduralCFG)."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
UTILS_FILE = "src/marshmallow/utils.py"
FIELDS_FILE = "src/marshmallow/fields.py"
CLASSES = ("_TemporalField", "DateTime", "NaiveDateTime")
TARGET = "marshmallow.fields.NaiveDateTime._deserialize"

LINE_RE = re.compile(r"^\S+ \S+ (?P<path>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = """\
Test file: `marshmallow_qa/fields_deserialize_m6_calls_3/files/testcase.py`, test class `TestNaiveDateTimeDeserialize`. Run ALL test methods of that class (pytest ids `marshmallow_qa/fields_deserialize_m6_calls_3/files/testcase.py::TestNaiveDateTimeDeserialize::<method>`, every `test_*` method in the class; all of them pass). The tests call the target `NaiveDateTime._deserialize` (defined in `src/marshmallow/fields.py`) directly, plus a few other field methods.

Scope (the tracked set of functions), resolved from the repository source as it exists:
  (a) every function defined at module level in `src/marshmallow/utils.py` (including names that start with an underscore), and
  (b) every method whose `def` appears directly in the class body of `_TemporalField`, of `DateTime`, or of `NaiveDateTime` in `src/marshmallow/fields.py` -- including `__init__`, static methods and abstract methods. Methods these classes merely inherit (e.g. anything defined only in `Field`) are NOT in scope unless redefined in one of these three class bodies; a method redefined in several of these classes yields one separate entry per defining class. Class attributes that merely hold references to callables (such as the values of the SERIALIZATION_FUNCS / DESERIALIZATION_FUNCS dicts, which point at standard-library functions or at the utils functions themselves) do not create extra entries; calls to functions outside the scope (standard library, `Field.make_error`, `ValidationError`, etc.) are not counted. There are no nested functions, lambdas or closures in scope; comprehension frames are never counted as separate functions.

Identity: `func` = `<runtime module name>.<qualname>` where the module name is the importable package path (no `src.` prefix), e.g. a method `bar` of a class `Foo` in `src/marshmallow/schema.py` would be `marshmallow.schema.Foo.bar`, and a module-level function `baz` in that file would be `marshmallow.schema.baz`. `file` = the repo-relative path of the defining file (`src/marshmallow/utils.py` or `src/marshmallow/fields.py`).

Counting: one invocation = one Python `call` event for a frame executing that function's code object (as `sys.settrace` would report it), counting every call regardless of who made it -- calls from the test code, from other in-scope functions, via `super()`, via dict lookup of a format function, or from anywhere else. A call that ends by raising an exception still counts once. None of the in-scope functions are generators or coroutines, so there are no resumption events to consider. Counts are SUMMED over all test methods of the class (one aggregate number per function, not per method). Functions in scope that never execute must still appear, with `count: 0`.

Answer format: {"invocation_counts": [{"count": <int>, "file": <str>, "func": <str>}, ...]} with exactly one entry per in-scope function, sorted by `func` ascending (plain Python string ordering, i.e. by Unicode code point; qualnames are unique so no tie-break is needed). `count` is a JSON integer."""


def scope_functions():
    out = []
    utils_tree = ast.parse((ROOT / UTILS_FILE).read_text(encoding="utf-8"))
    for node in utils_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((UTILS_FILE, f"marshmallow.utils.{node.name}"))
    fields_tree = ast.parse((ROOT / FIELDS_FILE).read_text(encoding="utf-8"))
    found = set()
    for node in fields_tree.body:
        if isinstance(node, ast.ClassDef) and node.name in CLASSES:
            found.add(node.name)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((FIELDS_FILE, f"marshmallow.fields.{node.name}.{item.name}"))
    if found != set(CLASSES):
        sys.exit(f"ERROR: classes not found in {FIELDS_FILE}: {set(CLASSES) - found}")
    if len(set(out)) != len(out):
        sys.exit("ERROR: duplicate qualnames in scope")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file() or path.stat().st_size == 0:
        sys.exit(f"ERROR: trace log missing or empty: {path}")

    scope = scope_functions()
    counts = {key: 0 for key in scope}
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m or m.group("event") != "call":
            continue
        fpath = m.group("path").replace("\\", "/")
        for rel in (UTILS_FILE, FIELDS_FILE):
            if fpath.endswith("/" + rel):
                key = (rel, m.group("func"))
                if key in counts:
                    counts[key] += 1
                break

    if counts.get((FIELDS_FILE, TARGET), 0) == 0:
        sys.exit(f"ERROR: zero call events for target {TARGET}")

    answer = [
        {"count": counts[key], "file": key[0], "func": key[1]}
        for key in sorted(counts, key=lambda k: k[1])
    ]
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"invocation_counts": [{"count": "int", "file": "str", "func": "str"}]},
        "oracle_answer": {"invocation_counts": answer},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
