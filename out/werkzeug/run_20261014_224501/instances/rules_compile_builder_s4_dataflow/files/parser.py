#!/usr/bin/env python
"""Derive observed def-use pairs of Rule._compile_builder from a line trace."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "src/werkzeug/routing/rules.py"
CLASS_NAME = "Rule"
FUNC_NAME = "_compile_builder"
QUALNAME_SUFFIX = "Rule._compile_builder"
TRACKED = [
    "append_unknown", "arg", "body", "code", "data", "defaults", "dom_ops",
    "dom_parts", "func_ast", "is_dynamic", "kargs", "module", "node", "opl",
    "pargs", "url_ops", "url_parts",
]
TEST_ID = (
    "werkzeug_qa/rules_compile_builder_s4_dataflow/files/testcase.py"
    "::CompileBuilderDataFlowTest::test_host_rules_build"
)

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""Consider the pytest test `{TEST_ID}` (file `werkzeug_qa/rules_compile_builder_s4_dataflow/files/testcase.py`, class `CompileBuilderDataFlowTest`, single test method `test_host_rules_build`). During this test, the method `werkzeug.routing.rules.Rule._compile_builder` defined in `src/werkzeug/routing/rules.py` is invoked many times (indirectly, while the Map binds its rules). An invocation is one call of that method; consider ALL invocations made during the test.

Report every unique dynamic def-use pair observed for these local variables of `_compile_builder` (and only these): {", ".join(f"`{v}`" for v in TRACKED)}.

Definitions (static name occurrences, attributed to statements; line numbers are absolute 1-based line numbers in `src/werkzeug/routing/rules.py` as it exists in the repository):
- Statement line: every statement of `_compile_builder` is identified by the line on which it begins. For a multi-line statement, all occurrences anywhere inside it (including inside a list comprehension that is part of it) are attributed to its first line. For `if`/`elif` the statement is only the header test expression (attributed to the `if`/`elif` line); for a `for` loop the statement is only the header (target + iterable, attributed to the `for` line). Bodies of the nested functions defined inside `_compile_builder` (`_convert`, `_parts`, `_join`) belong to other functions and are ignored entirely; only names of `_compile_builder`'s own frame count.
- Def: the variable is bound by an assignment target in the statement (`x = ...`), or as a `for` loop target (each time the `for` header binds a new element, i.e. every iteration; the final header evaluation that finds the iterable exhausted binds nothing). Parameters (`append_unknown`) are defined at the line of the `def` keyword when the invocation starts. Attribute or subscript assignment such as `x.attr = v` or `x.append(...)` is NOT a def of `x`; it is a use of `x`.
- Use: the variable name appears in a read (load) context anywhere in the executed statement, including as the base object of an attribute/subscript/method call (e.g. `x.y = 1` reads `x`). A use counts whenever the statement executes, regardless of short-circuit evaluation of `and`/`or` (every load occurrence in an executed `if`/`elif` test counts). Names bound by a comprehension's own `for` clause are comprehension-local and are different variables: an occurrence of such a name inside that comprehension is neither a def nor a use of the like-named function local (e.g. in `[a for a in xs]`, only `xs` is a use of a function local). Augmented assignment `x += 1` would count as a use of the old def AND a new def on that line (none of the tracked variables is augmented-assigned here).
- Within one statement, uses are evaluated before defs (so in `x = f(x)` the `x` use is reached by the previous def of `x`).
- A pair (variable, def_line, use_line) is observed when, in some invocation, a statement at use_line uses the variable and the most recent def of that variable executed earlier in the same invocation is at def_line. Pairs never cross invocations. If no def has executed yet in the invocation, no pair is recorded.

Answer format: a JSON object `{{"observed_def_use_pairs": [...]}}` where each element is an object with exactly the keys `variable` (string, the bare variable name), `def_line` (int), `use_line` (int). Each distinct triple appears once (deduplicate across all iterations and invocations). Sort ascending by `variable` (plain string comparison), then by `def_line`, then by `use_line`."""


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


class StmtInfo:
    def __init__(self, line, uses, defs, is_for, multiline):
        self.line = line
        self.uses = uses
        self.defs = defs
        self.is_for = is_for
        self.multiline = multiline
        self.body_lines = set()


def comp_scoped_names(node):
    """Collect (Name node ids) that are comprehension-local occurrences."""
    excluded = set()

    def visit(n, bound):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            new_bound = set(bound)
            for i, gen in enumerate(n.generators):
                # iterable of first generator is evaluated in enclosing scope
                visit(gen.iter, bound if i == 0 else new_bound)
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        new_bound.add(t.id)
                        excluded.add(id(t))
                for cond in gen.ifs:
                    visit(cond, new_bound)
            elts = [n.key, n.value] if isinstance(n, ast.DictComp) else [n.elt]
            for e in elts:
                visit(e, new_bound)
            return
        if isinstance(n, ast.Name) and n.id in bound:
            excluded.add(id(n))
        for c in ast.iter_child_nodes(n):
            visit(c, bound)

    visit(node, set())
    return excluded


def names_in(nodes):
    uses, defs = set(), set()
    for root in nodes:
        excl = comp_scoped_names(root)
        for n in ast.walk(root):
            if isinstance(n, ast.Name) and id(n) not in excl:
                if isinstance(n.ctx, ast.Load):
                    uses.add(n.id)
                elif isinstance(n.ctx, ast.Store):
                    defs.add(n.id)
    return uses, defs


def build_stmt_map(func):
    line_to_stmt = {}
    stmts = []

    def add(stmt_line, end_line, parts, is_for, extra_lines=None):
        uses, defs = names_in(parts)
        info = StmtInfo(stmt_line, uses, defs, is_for, end_line > stmt_line)
        stmts.append(info)
        for ln in range(stmt_line, end_line + 1):
            line_to_stmt.setdefault(ln, info)

    def walk(body):
        for s in body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # only the def statement itself (decorators/annotations) runs here
                add(s.lineno, s.lineno, [], False)
                continue
            if isinstance(s, ast.If):
                add(s.lineno, s.test.end_lineno, [s.test], False)
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.For):
                uses, _ = names_in([s.iter])
                _, defs = names_in([s.target])
                info = StmtInfo(s.lineno, uses, defs, True, False)
                info.body_lines = set(range(s.body[0].lineno, s.body[-1].end_lineno + 1))
                stmts.append(info)
                for ln in range(s.lineno, s.iter.end_lineno + 1):
                    line_to_stmt.setdefault(ln, info)
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, (ast.While, ast.With, ast.Try)):
                die(f"unsupported compound statement at {s.lineno}")
            else:
                add(s.lineno, s.end_lineno, [s], False)

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
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == FUNC_NAME:
                    func = item
    if func is None:
        die("target function not found in source")
    def_line = func.lineno
    params = [a.arg for a in func.args.args + func.args.kwonlyargs if a.arg != "self"]
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
    pending_for = None  # for-header executed; binding confirmed if body follows
    n_calls = 0
    n_lines = 0

    def flush_for(next_line):
        nonlocal pending_for
        if pending_for is None:
            return
        stmt = pending_for
        pending_for = None
        # header bound an element only if execution moved into the loop body
        body_entered = next_line is not None and stmt.body_lines and next_line in stmt.body_lines
        if body_entered:
            for v in stmt.defs:
                reaching[v] = stmt.line

    for ev, line in events:
        if ev == "call":
            n_calls += 1
            reaching = {p: def_line for p in params}
            prev_stmt = None
            pending_for = None
            continue
        if reaching is None:
            die("line event before call event")
        if ev in ("return", "exception"):
            if ev == "return":
                flush_for(None)
                reaching = None
                prev_stmt = None
            continue
        if ev != "line":
            continue
        n_lines += 1
        stmt = line_to_stmt.get(line)
        if stmt is None:
            die(f"executed line {line} not mapped to a statement")
        flush_for(line)
        if stmt is prev_stmt and stmt.multiline:
            continue  # continuation event of the same multi-line statement
        prev_stmt = stmt
        for v in stmt.uses:
            if v in TRACKED and v in reaching:
                pairs.add((v, reaching[v], stmt.line))
        if stmt.is_for:
            pending_for = stmt
        else:
            for v in stmt.defs:
                reaching[v] = stmt.line

    if n_calls == 0 or n_lines == 0:
        die("no call/line events for target function")

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v}
            for v, d, u in sorted(pairs)
            if v in TRACKED
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
