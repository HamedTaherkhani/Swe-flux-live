#!/usr/bin/env python
"""Trace -> oracle.json for map_match_s5_exceptions (S5_Exceptions, template 2).

Answer: sorted set of exception types that were caught by an ``except``
clause of ``MapAdapter.match`` itself across every invocation in the test.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET_REL = "src/werkzeug/routing/map.py"
TARGET_MODULE = "werkzeug.routing.map"
TARGET_QUALNAME = "MapAdapter.match"
TARGET_FUNC = f"{TARGET_MODULE}.{TARGET_QUALNAME}"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>[^:]+):)?"
)

QUESTION = (
    "Consider the pytest test "
    "`werkzeug_qa/map_match_s5_exceptions/files/testcase.py::RoutingDispatchTest::test_dispatch_matrix` "
    "(file `werkzeug_qa/map_match_s5_exceptions/files/testcase.py`, class `RoutingDispatchTest`, "
    "single test method `test_dispatch_matrix`). During this one test run, the method "
    "`werkzeug.routing.map.MapAdapter.match` (defined in `src/werkzeug/routing/map.py`) is invoked "
    "many times, always indirectly (through `MapAdapter.dispatch` from the WSGI app driven by the test "
    "client, and through `MapAdapter.test` / `MapAdapter.allowed_methods`). Over ALL invocations of "
    "`MapAdapter.match` during the test (every call of the method counts; an invocation is one call), "
    "which exception types were CAUGHT by one of the `except` clauses written in the body of "
    "`MapAdapter.match` itself? An exception counts only if it propagated into the frame of "
    "`MapAdapter.match` (i.e. was raised inside the `try` block of that method, including from callees) "
    "and execution then entered the body of one of that method's own `except` handlers. Do NOT count: "
    "exceptions raised by `MapAdapter.match` (e.g. by its `raise` statements) that leave the method; "
    "exceptions that propagate through `MapAdapter.match` uncaught; exceptions raised and handled entirely "
    "inside callees (e.g. inside the matcher or converters) that never reach the frame of "
    "`MapAdapter.match`; or exceptions handled by the callers. Report the concrete runtime type of the "
    "caught exception object (`type(exc)`), not the class named in the `except` clause, if they differ. "
    "Naming convention: for built-in exceptions use the bare `type(exc).__name__` (e.g. `ValueError`, "
    "never `builtins.ValueError`); for all other exceptions use `type(exc).__module__ + '.' + "
    "type(exc).__qualname__` (e.g. `http.client.HTTPException`), i.e. the module where the class is "
    "defined, not a re-exporting module. Each type is listed once (deduplicated) no matter how many times "
    "it was caught, and the list is sorted in ascending lexicographic (Python default string) order. "
    'Answer as JSON: {"caught_exception_kinds": [<str>, ...]}.'
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_try_structure():
    src = (ROOT / TARGET_REL).read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MapAdapter":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "match":
                    func = item
    if func is None:
        fail("could not locate MapAdapter.match in source")
    tries = []
    for node in ast.walk(func):
        if isinstance(node, ast.Try):
            body_lines = set()
            for stmt in node.body:
                body_lines.update(range(stmt.lineno, stmt.end_lineno + 1))
            handlers = []
            for h in node.handlers:
                if h.type is None:
                    type_names = None
                elif isinstance(h.type, ast.Tuple):
                    type_names = [ast.unparse(e) for e in h.type.elts]
                else:
                    type_names = [ast.unparse(h.type)]
                hbody = set()
                for stmt in h.body:
                    hbody.update(range(stmt.lineno, stmt.end_lineno + 1))
                handlers.append({"header": h.lineno, "body": hbody, "types": type_names})
            tries.append({"body": body_lines, "handlers": handlers})
    return tries


def all_subclasses(cls):
    out = [cls]
    for sub in cls.__subclasses__():
        out.extend(all_subclasses(sub))
    return out


def format_type(cls) -> str:
    if cls.__module__ == "builtins":
        return cls.__name__
    return f"{cls.__module__}.{cls.__qualname__}"


def resolve(exc_name: str, handler_types) -> str:
    sys.path.insert(0, str(ROOT / "src"))
    mod = importlib.import_module(TARGET_MODULE)
    candidates = []
    roots = []
    if handler_types is None:
        roots = [BaseException]
    else:
        for tn in handler_types:
            obj = mod
            for part in tn.split("."):
                obj = getattr(obj, part, None) if obj is not None else None
            if obj is None:
                obj = getattr(__import__("builtins"), tn, None)
            if obj is None:
                fail(f"cannot resolve handler type {tn!r}")
            roots.append(obj)
    for r in roots:
        for c in all_subclasses(r):
            if c.__name__ == exc_name and c not in candidates:
                candidates.append(c)
    if len(candidates) != 1:
        fail(f"ambiguous/unresolvable exception type {exc_name!r}: {candidates}")
    return format_type(candidates[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    raw = path.read_text(encoding="utf-8").splitlines()
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m or m.group("func") != TARGET_FUNC:
            continue
        if not m.group("file").endswith(TARGET_REL):
            continue
        events.append(
            (int(m.group("lineno")), m.group("event"), (m.group("exc") or "").strip())
        )
    if not events:
        fail("no trace events for target function")
    if not any(e[1] == "call" for e in events):
        fail("no call events for target function")

    tries = load_try_structure()
    caught = set()
    n_calls = 0
    pending = None  # (exc_name, try_info)
    for lineno, event, exc in events:
        if event == "call":
            n_calls += 1
            pending = None
            continue
        if event == "exception":
            pending = None
            for tr in tries:
                if lineno in tr["body"]:
                    pending = (exc, tr)
                    break
            continue
        if pending is None:
            continue
        if event == "return":
            pending = None
            continue
        exc_name, tr = pending
        headers = {h["header"] for h in tr["handlers"]}
        if lineno in headers:
            continue
        for h in tr["handlers"]:
            if lineno in h["body"]:
                caught.add(resolve(exc_name, h["types"]))
                break
        pending = None

    answer = {"caught_exception_kinds": sorted(caught)}
    if not answer["caught_exception_kinds"]:
        fail("no caught exceptions found; scenario broken")
    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": answer,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(answer, sort_keys=True))
    print(f"invocations={n_calls}")


if __name__ == "__main__":
    main()
