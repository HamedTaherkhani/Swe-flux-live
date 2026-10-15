#!/usr/bin/env python
"""Derive observed def-use pairs of CmaEsSampler.sample_relative from a line trace."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/samplers/_cmaes.py"
TARGET_CLASS = "CmaEsSampler"
TARGET_METHOD = "sample_relative"
TARGET_QUALNAME = "optuna.samplers._cmaes.CmaEsSampler.sample_relative"
TEST_PATH = "optuna_qa/cmaes_sample_relative_s4_dataflow/files/testcase.py"
TEST_CLASS = "TestCmaEsSampleRelativeDataFlow"
TEST_METHOD = "test_sample_relative_two_samplers"

TRACKED = sorted(
    [
        "study",
        "trial",
        "search_space",
        "completed_trials",
        "trans",
        "optimizer",
        "ind_sampler_name",
        "solution_trials",
        "solutions",
        "t",
        "x",
        "y",
        "optimizer_str",
        "optimizer_attrs",
        "key",
        "seed",
        "params",
        "x_for_tell",
        "generation_attr_key",
        "external_values",
    ]
)

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} (?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def names(node: ast.AST | None, ctx: type) -> set[str]:
    if node is None:
        return set()
    return {
        n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)
    }


def build_statement_map(source: str):
    tree = ast.parse(source)
    func = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_METHOD:
                    func = item
    if func is None:
        fail("target function not found in source")

    # Each entry: (start_line, end_line_of_header, uses, defs)
    stmts: list[tuple[int, int, set[str], set[str]]] = []

    def visit(body: list[ast.stmt]) -> None:
        for st in body:
            if isinstance(st, ast.If):
                stmts.append((st.lineno, st.test.end_lineno, names(st.test, ast.Load), set()))
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, ast.For):
                stmts.append(
                    (
                        st.lineno,
                        st.iter.end_lineno,
                        names(st.iter, ast.Load),
                        names(st.target, ast.Store),
                    )
                )
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, (ast.While, ast.With, ast.Try, ast.FunctionDef, ast.ClassDef)):
                fail(f"unsupported compound statement at line {st.lineno}")
            else:
                uses = names(st, ast.Load)
                defs = names(st, ast.Store)
                if isinstance(st, ast.AnnAssign):
                    uses -= names(st.annotation, ast.Load) - names(st.value, ast.Load)
                if isinstance(st, ast.AugAssign):
                    uses |= names(st.target, ast.Store)
                stmts.append((st.lineno, st.end_lineno, uses, defs))

    visit(func.body)
    params = {a.arg for a in func.args.args + func.args.kwonlyargs}
    line_to_stmt: dict[int, int] = {}
    info: dict[int, tuple[set[str], set[str]]] = {}
    for start, end, uses, defs in stmts:
        info[start] = (uses, defs)
        for ln in range(start, end + 1):
            if ln in line_to_stmt:
                fail(f"overlapping statement ranges at line {ln}")
            line_to_stmt[ln] = start
    return func.lineno, params, line_to_stmt, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log empty: {args.trace_log}")

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(os.getcwd(), TARGET_REL)]
    p = here
    for _ in range(5):
        p = os.path.dirname(p)
        candidates.append(os.path.join(p, TARGET_REL))
    src_path = next((c for c in candidates if os.path.isfile(c)), None)
    if src_path is None:
        fail("could not locate target source file")
    with open(src_path, encoding="utf-8") as fh:
        source = fh.read()
    def_line, params, line_to_stmt, info = build_statement_map(source)

    invocations: list[list[int]] = []
    current: list[int] | None = None
    n_events = 0
    with open(args.trace_log, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
                continue
            if m.group("func") != TARGET_QUALNAME:
                continue
            n_events += 1
            ev = m.group("event")
            ln = int(m.group("line"))
            if ev == "call":
                if current is not None:
                    fail("nested/unterminated invocation in trace")
                current = []
            elif ev == "line":
                if current is None:
                    fail("line event outside an invocation")
                current.append(ln)
            elif ev == "exception":
                fail(f"unexpected exception event at line {ln}")
            elif ev == "return":
                if current is None:
                    fail("return event outside an invocation")
                invocations.append(current)
                current = None
    if n_events == 0:
        fail("trace contains zero events for the target function")
    if current is not None:
        fail("trace ended inside an invocation")
    if not invocations:
        fail("no complete invocations of the target in the trace")

    tracked = set(TRACKED)
    pairs: set[tuple[str, int, int]] = set()
    for lines in invocations:
        reaching: dict[str, int] = {v: def_line for v in params if v in tracked}
        prev_stmt = None
        for ln in lines:
            stmt = line_to_stmt.get(ln)
            if stmt is None:
                fail(f"executed line {ln} does not map to a statement")
            if stmt == prev_stmt:
                continue  # continuation line of the same statement execution
            prev_stmt = stmt
            uses, defs = info[stmt]
            for v in uses & tracked:
                if v in reaching:
                    pairs.add((v, reaching[v], stmt))
            for v in defs & tracked:
                reaching[v] = stmt

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for v, d, u in sorted(pairs)
        ]
    }
    if not answer["observed_def_use_pairs"]:
        fail("no def-use pairs computed")

    var_list = ", ".join(f"`{v}`" for v in TRACKED)
    question = (
        f"Run the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (test class "
        f"`{TEST_CLASS}` in `{TEST_PATH}`; the answer covers only this single test method). "
        f"During that run, consider every invocation of `{TARGET_QUALNAME}` (method "
        f"`CmaEsSampler.sample_relative` defined in `{TARGET_REL}`, `def` at line {def_line}); "
        "an invocation is one call of the method, and the method is called on two different "
        "sampler instances during the test - all invocations are aggregated. "
        "Report every unique dynamic def-use pair that is actually observed at runtime for "
        f"these local variables only (exact names): {var_list}. "
        "Definitions: a 'def' of a variable is a binding of that name in the method's own frame: "
        "an assignment statement (including an annotated assignment with a value) whose target is "
        "the bare name, or a `for` loop target (the `for` header line re-defines the loop variable "
        "on every iteration). The parameters `study`, `trial` and `search_space` are defined at "
        f"the `def` line ({def_line}) at the start of every invocation; `self` is not tracked. "
        "A 'use' is any read of the variable's value on a statement, including as a call "
        "argument, as the receiver of an attribute access or method call (e.g. "
        "`foo.append(v)` or `foo.bar` is a use of `foo`, not a def), in subscripts, conditions, "
        "f-strings, `assert` and `return` expressions. Mutating an object through a method or "
        "attribute is never a def. Augmented assignment (`v += 1`) would count as a use of the "
        "old def AND a new def on that line (none occurs in this method). For `if` statements "
        "the use is on the `if` line (the condition); for a `for` statement the iterable "
        "expression's reads are uses on the `for` line. There are no comprehensions in this "
        "method; names read inside other functions are irrelevant - only the method's own "
        "frame counts. Within a statement, all reads happen before the statement's binding. "
        "A pair (variable, def_line, use_line) is observed when, in some invocation, the value "
        "bound at def_line is still the most recent binding of that variable in that "
        "invocation's frame when the statement at use_line reads it. Bindings never carry over "
        "between invocations. Line numbers are absolute 1-based line numbers in "
        f"`{TARGET_REL}` as it exists in the repository; for a statement spanning several "
        "physical lines, both its def_line and use_line are the line where the statement "
        "begins (for `if`/`for`, the header line). "
        "Answer format: a JSON object with a single key `observed_def_use_pairs` whose value is "
        "a list of objects, each with exactly the keys `variable` (string, the bare variable "
        "name), `def_line` (integer) and `use_line` (integer). Each distinct (variable, "
        "def_line, use_line) triple appears exactly once no matter how often it was observed. "
        "Sort the list by `variable` (ascending, plain string comparison), then `def_line` "
        "ascending, then `use_line` ascending. Include only pairs actually observed at runtime "
        "in this test run (pairs that are possible statically but never happen must be omitted)."
    )

    oracle = {
        "question_kind": "S4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
        },
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    print(
        f"invocations={len(invocations)} line_events={sum(len(x) for x in invocations)} "
        f"distinct_lines={len({l for x in invocations for l in x})} pairs={len(pairs)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
