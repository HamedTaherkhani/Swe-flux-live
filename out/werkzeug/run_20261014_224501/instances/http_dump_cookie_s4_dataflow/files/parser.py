#!/usr/bin/env python
"""Derive observed def-use pairs of werkzeug.http.dump_cookie from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/http.py"
FUNC_NAME = "dump_cookie"
QUALNAME_SUFFIX = "http.dump_cookie"
TRACKED = [
    "buf", "cookie_size", "domain", "expires", "httponly", "k", "key",
    "max_age", "max_size", "partitioned", "path", "rv", "samesite", "secure",
    "sync_expires", "v", "value", "value_size",
]
TEST_FILE = "werkzeug_qa/http_dump_cookie_s4_dataflow/files/testcase.py"
TEST_ID = f"{TEST_FILE}::DumpCookieDataFlowTest::test_dump_cookie_batch"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""Consider the pytest test `{TEST_ID}` (file `{TEST_FILE}`, class `DumpCookieDataFlowTest`, single test method `test_dump_cookie_batch`). During this test the function `werkzeug.http.dump_cookie` defined in `src/werkzeug/http.py` is called directly many times with programmatically generated arguments (some calls raise `ValueError`, some emit warnings). An invocation is one call of `dump_cookie`; consider ALL invocations made during the test, in chronological order, including the ones that end by raising.

Report every unique dynamic def-use pair observed for these local variables of `dump_cookie` (and only these): {", ".join(f"`{v}`" for v in TRACKED)}.

Definitions (line numbers are absolute, 1-based line numbers in `src/werkzeug/http.py` as it exists in the repository):
- Statement line: every statement of `dump_cookie` is identified by the line on which it begins. For a multi-line statement, every name occurrence anywhere inside it is attributed to its first line (e.g. a call whose arguments span several lines is entirely attributed to the line holding the start of the statement). For `if`/`elif` the statement is only the header test expression (attributed to the `if`/`elif` line). For the `for` loop the statement is only the header, i.e. the loop target plus the whole iterable expression (even though the iterable spans several lines), attributed to the `for` line. The body of the `lambda` inside `dump_cookie` belongs to a different function and is ignored (its own parameter and globals are not locals of `dump_cookie`). Docstring lines never appear.
- Def: the variable is bound by an assignment target in an executed statement (`x = ...`), or as a `for` loop target each time the `for` header binds a new element (every iteration; the final header evaluation that finds the iterable exhausted binds nothing). All parameters are defined at the line of the `def` keyword (the line `def dump_cookie(`) when the invocation starts, whether passed explicitly or taken from defaults. Method calls such as `x.append(...)` are NOT a def of `x`; they are a use of `x`. Augmented assignment `x += 1` would count as both a use of the old def and a new def on that line (none occurs here).
- Use: the variable name appears in a read (load) context anywhere in the executed statement, including as the base object of an attribute access or method call and inside f-string replacement fields. A use counts whenever the statement executes, regardless of short-circuit evaluation of `and`/`or` (every load occurrence in an executed `if`/`elif` test counts, even if Python did not actually evaluate that operand). There are no comprehensions in this function.
- Within one statement, uses are evaluated before defs (so in `x = f(x)` the `x` use is reached by the previous def of `x`).
- A pair (variable, def_line, use_line) is observed when, in some invocation, an executed statement at use_line uses the variable and the most recent def of that variable executed earlier in the same invocation is at def_line. Pairs never cross invocations. A statement only counts as executed if execution actually reached it (an invocation that raises stops at the raising statement; statements after it are not executed).

Answer format: a JSON object `{{"observed_def_use_pairs": [...]}}` where each element is an object with exactly the keys `variable` (string, the bare variable name), `def_line` (int), `use_line` (int). Each distinct triple appears once (deduplicate across all iterations and invocations). Sort ascending by `variable` (plain string comparison), then by `def_line`, then by `use_line`."""


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


class StmtInfo:
    def __init__(self, line, uses, defs, is_for):
        self.line = line
        self.uses = uses
        self.defs = defs
        self.is_for = is_for
        self.body_lines = set()


def names_in(nodes):
    uses, defs = set(), set()

    def visit(n):
        if isinstance(n, ast.Lambda):
            # only default expressions are evaluated in the enclosing frame
            for d in n.args.defaults + [d for d in n.args.kw_defaults if d]:
                visit(d)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            die("unexpected comprehension in target function")
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ast.Load):
                uses.add(n.id)
            elif isinstance(n.ctx, ast.Store):
                defs.add(n.id)
        for c in ast.iter_child_nodes(n):
            visit(c)

    for root in nodes:
        visit(root)
    return uses, defs


def build_stmt_map(func):
    line_to_stmt = {}

    def register(info, start, end):
        for ln in range(start, end + 1):
            if ln in line_to_stmt:
                die(f"line {ln} mapped twice")
            line_to_stmt[ln] = info

    def walk(body):
        for s in body:
            if isinstance(s, ast.If):
                uses, defs = names_in([s.test])
                register(StmtInfo(s.lineno, uses, defs, False), s.lineno, s.test.end_lineno)
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.For):
                uses, _ = names_in([s.iter])
                _, defs = names_in([s.target])
                info = StmtInfo(s.lineno, uses, defs, True)
                info.body_lines = set(range(s.body[0].lineno, s.body[-1].end_lineno + 1))
                register(info, s.lineno, s.iter.end_lineno)
                walk(s.body)
                if s.orelse:
                    die("for/else unsupported")
            elif isinstance(s, (ast.While, ast.With, ast.Try, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef)):
                die(f"unsupported compound statement at {s.lineno}")
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) \
                    and isinstance(s.value.value, str) and s is func.body[0]:
                continue  # docstring
            else:
                uses, defs = names_in([s])
                register(StmtInfo(s.lineno, uses, defs, False), s.lineno, s.end_lineno)

    walk(func.body)
    return line_to_stmt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=TARGET_REL)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        die("trace log is empty")

    with open(args.source, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            func = node
    if func is None:
        die("target function not found in source")
    def_line = func.lineno
    a = func.args
    params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    line_to_stmt = build_stmt_map(func)

    events = []
    for ln in raw:
        m = LINE_RE.match(ln)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if not m.group("func").endswith(QUALNAME_SUFFIX):
            continue
        events.append((m.group("event"), int(m.group("line"))))
    if not events:
        die("no trace events for target function")

    pairs = set()
    reaching = None
    prev_stmt = None
    pending_for = None
    n_calls = n_lines = 0

    def flush_for(next_line):
        nonlocal pending_for
        if pending_for is None:
            return
        stmt, pending_for = pending_for, None
        if next_line is not None and next_line in stmt.body_lines:
            for v in stmt.defs:
                reaching[v] = stmt.line

    for ev, line in events:
        if ev == "call":
            if reaching is not None:
                die("nested/unterminated invocation")
            n_calls += 1
            reaching = {p: def_line for p in params}
            prev_stmt = None
            pending_for = None
            continue
        if reaching is None:
            die(f"{ev} event outside invocation")
        if ev == "return":
            flush_for(None)
            reaching = None
            prev_stmt = None
            continue
        if ev != "line":
            continue  # exception events: the invocation ends with the following return
        n_lines += 1
        stmt = line_to_stmt.get(line)
        if stmt is None:
            die(f"executed line {line} not mapped to a statement")
        if stmt is prev_stmt:
            continue  # continuation event of the same (multi-line) statement execution
        flush_for(line)
        prev_stmt = stmt
        for v in stmt.uses:
            if v in TRACKED and v in reaching:
                pairs.add((v, reaching[v], stmt.line))
        if stmt.is_for:
            pending_for = stmt
        else:
            for v in stmt.defs:
                reaching[v] = stmt.line

    if reaching is not None:
        die("trace ended inside an invocation")
    if n_calls == 0 or n_lines == 0:
        die("no call/line events for target function")

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v}
            for v, d, u in sorted(pairs)
        ]
    }
    if not answer["observed_def_use_pairs"]:
        die("no def-use pairs computed")
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={n_calls} line_events={n_lines} pairs={len(answer['observed_def_use_pairs'])}")


if __name__ == "__main__":
    main()
