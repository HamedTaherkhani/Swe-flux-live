#!/usr/bin/env python
"""Harvest per-function invocation counts for networkx/readwrite/gml.py."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/readwrite/gml.py"
MODULE = "networkx.readwrite.gml"
TARGET_QUAL = "networkx.readwrite.gml.generate_gml.<locals>.stringize"

TEST_PATH = "networkx_qa/gml_stringize_m6_calls/files/testcase.py"
TEST_CLASS = "TestGmlWriterScenarios"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = f"""\
Test file: `{TEST_PATH}`, test class `{TEST_CLASS}`. Run ALL test methods of this class \
(every `test_*` method; pytest ids of the form `{TEST_PATH}::{TEST_CLASS}::<method>`) and \
aggregate over all of them; the answer is a single total per function, not per method.

The writer path exercised here ends in the nested generator `generate_gml.<locals>.stringize` \
in `networkx/readwrite/gml.py` (module `networkx.readwrite.gml`), reached via `nx.write_gml`, \
`nx.generate_gml` and the parsing round trips in the tests.

Scope: consider every function defined with `def` anywhere in `networkx/readwrite/gml.py`: all \
module-level functions AND all functions nested inside other functions (closures / inner \
functions at any depth). The file defines no methods inside its classes, so nothing from class \
bodies is in scope. Excluded: lambdas, comprehension and generator-expression frames \
(`<genexpr>`, `<listcomp>`, ...), the module body itself, and any function defined in other \
files (e.g. the decorators' wrapper functions in `networkx/utils`, the dispatch machinery, \
`re`, builtins).

Identity: `func` is the module name followed by the function's Python `__qualname__`, joined by \
a dot, with `<locals>` segments kept exactly as Python writes them. Example format (not \
necessarily part of the answer): a function `inner` defined inside module-level `outer` in \
module `pkg.mod` is `pkg.mod.outer.<locals>.inner`. `file` is the repo-relative path \
`networkx/readwrite/gml.py` for every entry.

What counts as one invocation: one fresh call of the function, i.e. one new frame of that \
function starting to execute its body, whatever frame it is called from (directly, \
transitively, recursively, via callbacks such as `re.sub` replacement functions or a \
`stringizer`/`destringizer` argument, or via `yield from`). For generator functions, an \
invocation is counted once when the generator object first starts running (its first \
`next()`); every later resumption of the same suspended generator (each subsequent \
`next()`/`yield from` step after a `yield`) does NOT count again. A generator object that is \
created but never started is not counted. A call that ends by raising an exception still counts.

Zero rule: every in-scope function appears exactly once in the list, including those that never \
run during the test class (`count: 0`).

Output: `{{"invocation_counts": [{{"count": int, "file": str, "func": str}}, ...]}}`, sorted by \
`func` ascending (plain Python string ordering / codepoint order); qualnames are unique so no \
tie-break is needed. `count` is a JSON integer.
"""


def scope_functions(source_path: Path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    out = {}  # qualname -> first line (decorator line if decorated)

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qual = f"{prefix}{child.name}"
                first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                if qual in out:
                    raise SystemExit(f"ERROR: duplicate qualname {qual}")
                out[qual] = first
                visit(child, f"{qual}.<locals>.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return {f"{MODULE}.{q}": ln for q, ln in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=REL_FILE)
    args = ap.parse_args()

    log = Path(args.trace_log)
    if not log.is_file() or log.stat().st_size == 0:
        sys.exit(f"ERROR: trace log missing or empty: {log}")

    funcs = scope_functions(Path(args.source))
    counts = {q: 0 for q in funcs}
    target_events = 0
    for raw in log.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m or not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        func = m.group("func")
        if func == TARGET_QUAL:
            target_events += 1
        if m.group("event") != "call" or func not in funcs:
            continue
        # fresh frames start at the def/decorator line; generator resumptions
        # report the line of the suspended yield instead.
        if int(m.group("lineno")) == funcs[func]:
            counts[func] += 1

    if target_events == 0 or counts[TARGET_QUAL] == 0:
        sys.exit("ERROR: no events for target function in trace log")

    answer = {
        "invocation_counts": [
            {"count": counts[q], "file": REL_FILE, "func": q} for q in sorted(counts)
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
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=False) + "\n")
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
