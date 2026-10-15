#!/usr/bin/env python
"""Derive the S5_Exceptions oracle for stochastic_block_model from a trace log."""

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.generators.community.stochastic_block_model"
TARGET_FILE = "networkx/generators/community.py"
TEST_FILE = (
    "networkx_qa/community_stochastic_block_model_s5_exceptions/files/testcase.py"
)
TEST_CLASS = "TestGaussianPartitionTinyCrossProbability"
TEST_METHOD = "test_tiny_inter_cluster_probability"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][\w.]*): (?P<body>.*)$")

QUESTION = (
    f"Consider the pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` "
    f"(test class `{TEST_CLASS}` in file `{TEST_FILE}`, single test method "
    f"`{TEST_METHOD}`). During this test run, the function "
    f"`{TARGET_QUALNAME}` (defined in `{TARGET_FILE}`) is invoked exactly once "
    "(reached indirectly through the public generator called by the test; an "
    "invocation is one call of that function's own frame, not of the dispatch/"
    "decorator wrappers around it). In that invocation an exception is raised "
    "that is NOT handled inside `stochastic_block_model` and propagates out of "
    "its frame to its caller. Report that single propagated exception (i.e. the "
    "exception object that leaves the `stochastic_block_model` frame; exceptions "
    "that are raised and caught inside the function, e.g. ones that only end a "
    "loop, do not count). Answer as a JSON object with exactly two string keys: "
    "`exception_type` and `exception_message`. `exception_type` naming "
    "convention: use bare `type(exc).__name__` for built-in exceptions (e.g. "
    "`KeyError`, never `builtins.KeyError`), and the fully qualified "
    "`module.QualName` of the class for all non-built-in exceptions (e.g. "
    "`networkx.exception.NetworkXUnfeasible`, using the module where the class "
    "is defined, i.e. `type(exc).__module__ + '.' + type(exc).__qualname__`). "
    "`exception_message` must be exactly `str(exc)` of that exception object, "
    "character for character (no type prefix, no quotes, no traceback; an empty "
    "message would be the empty string)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def type_name(name):
    if isinstance(getattr(builtins, name, None), type) and issubclass(
        getattr(builtins, name), BaseException
    ):
        return name
    import networkx.exception as nxe

    cls = getattr(nxe, name, None)
    if isinstance(cls, type) and issubclass(cls, BaseException):
        return f"{cls.__module__}.{cls.__qualname__}"
    fail(f"cannot resolve module of non-builtin exception type {name!r}")


def except_header_lines():
    src_path = Path(__file__).resolve().parents[3] / TARGET_FILE
    if not src_path.is_file():
        src_path = Path.cwd() / TARGET_FILE
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "stochastic_block_model":
            return {
                h.lineno for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)
            }
    fail("target function not found in source")


def message_from_repr(body):
    if body.endswith("..."):
        fail("exception repr truncated in trace; cannot recover message")
    try:
        node = ast.parse(body, mode="eval").body
    except SyntaxError:
        fail(f"cannot parse exception repr: {body!r}")
    if not isinstance(node, ast.Call) or node.keywords:
        fail(f"unexpected exception repr shape: {body!r}")
    args = tuple(ast.literal_eval(a) for a in node.args)
    if len(args) == 0:
        return ""
    if len(args) == 1:
        return str(args[0])
    return str(args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ns = ap.parse_args()

    path = Path(ns.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        fail("trace log is empty")

    events = []
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        events.append(m)
    if not events:
        fail("no trace events for the target function")

    calls = [e for e in events if e.group("event") == "call"]
    if len(calls) != 1:
        fail(f"expected exactly one invocation, found {len(calls)}")

    # Propagated exception: an `exception` event after which the frame
    # returns having executed only `except ...:` header lines (non-matching
    # handler tests) => the exception was not handled.
    header_lines = except_header_lines()
    propagated = []
    for idx, ev in enumerate(events):
        if ev.group("event") != "exception":
            continue
        for nxt in events[idx + 1 :]:
            kind = nxt.group("event")
            if kind == "line" and int(nxt.group("line")) in header_lines:
                continue
            if kind == "return":
                propagated.append(ev)
            break
    if len(propagated) != 1:
        fail(f"expected one propagated exception, found {len(propagated)}")

    em = EXC_RE.match(propagated[0].group("rest").rsplit(" locals=", 1)[0])
    if not em:
        fail("cannot parse exception payload")
    answer = {
        "exception_message": message_from_repr(em.group("body")),
        "exception_type": type_name(em.group("name")),
    }

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": answer,
    }
    Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
    with open(ns.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
