#!/usr/bin/env python
"""Trace -> oracle.json for tree_get_marginalized_statistics_m6_calls (M6_InterProceduralCFG)."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_REL = "optuna/importance/_fanova/_tree.py"
MODULE = "optuna.importance._fanova._tree"
CLASS_NAME = "_FanovaTree"
TARGET_QUALNAME = f"{MODULE}.{CLASS_NAME}._get_marginalized_statistics"
TEST_FILE = "optuna_qa/tree_get_marginalized_statistics_m6_calls/files/testcase.py"
TEST_CLASS = "TestFanovaForestMarginals"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def scope_functions(src_path: Path) -> list[str]:
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(f"{MODULE}.{node.name}")
        elif isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.append(f"{MODULE}.{CLASS_NAME}.{sub.name}")
    if len(names) != len(set(names)):
        fail("duplicate qualnames in scope")
    return names


QUESTION = f"""\
Run ALL test methods of the test class `{TEST_CLASS}` in the file `{TEST_FILE}` (pytest id `{TEST_FILE}::{TEST_CLASS}`), all in one pytest process. The answer aggregates over every test method in that class (the totals do not depend on the order in which the methods run). Each test drives fANOVA importance evaluation through the public API, which eventually reaches the method `{TARGET_QUALNAME}` defined in `{TARGET_REL}`.

Consider every function and method defined in `{TARGET_REL}` (module `{MODULE}`): all module-level `def` functions of that file, and all methods defined directly in the body of class `{CLASS_NAME}` — this includes `__init__`, methods decorated with `@property` (the getter function counts as the method), and methods decorated with `functools.lru_cache`. Excluded: nested functions, lambdas, closures, comprehension frames (on the Python 3.11 interpreter used here, list comprehensions run in their own `<listcomp>` frames; those are NOT tracked), the module's top-level code, and anything inherited or defined in other files.

For EACH function in that scope, report how many times it was invoked during the whole run of the test class. One invocation = one Python `call` event for that function's own code object, i.e. the function's own body starts executing in a new frame — counted no matter who called it (directly from the test, transitively from any frame, from C code, or recursively). A call that never enters the function's body does NOT count: in particular, when a `functools.lru_cache`-decorated method is called and the cache already holds a result for those arguments, the cached value is returned by the C wrapper without executing the method's body, so that is not an invocation. None of the in-scope functions are generators or coroutines, so resumptions do not arise. Functions in scope that never execute must still appear, with `count` 0.

Answer format: a JSON object `{{"invocation_counts": [...]}}` where each element is `{{"count": <int>, "file": <str>, "func": <str>}}`:
- `file`: the repo-relative path `{TARGET_REL}` (forward slashes, no leading `./`).
- `func`: the dotted fully qualified name `<module>.<qualname>`, e.g. a method `bar` of class `Foo` in module `pkg.mod` is written `pkg.mod.Foo.bar`, and a module-level function `baz` is written `pkg.mod.baz`.
- `count`: a JSON integer (total over all test methods).
The list contains exactly one entry per in-scope function (no duplicates; qualnames are unique in this scope) and is sorted by `func` ascending using plain Python string ordering (code-point order, so e.g. uppercase letters sort before underscore, which sorts before lowercase letters).
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log not found: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    repo_root = Path(__file__).resolve().parents[3]
    src_path = repo_root / TARGET_REL
    if not src_path.is_file():
        src_path = Path("/testbed") / TARGET_REL
    scope = scope_functions(src_path)
    counts = {name: 0 for name in scope}

    target_events = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        func = m.group("func")
        if func == TARGET_QUALNAME:
            target_events += 1
        if m.group("event") == "call" and func in counts:
            counts[func] += 1

    if target_events == 0 or counts[TARGET_QUALNAME] == 0:
        fail(f"no trace events for target {TARGET_QUALNAME}")

    answer = {
        "invocation_counts": [
            {"count": counts[f], "file": TARGET_REL, "func": f} for f in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
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
