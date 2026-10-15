"""Derive the S5_Exceptions oracle for prim_mst_edges from the trace log."""

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.algorithms.tree.mst.prim_mst_edges"
TARGET_FILE = "networkx/algorithms/tree/mst.py"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/mst_prim_mst_edges_s5_exceptions/files/testcase.py::"
    "TestPrimNaNEdge::test_prim_maximum_hits_nan` (file "
    "`networkx_qa/mst_prim_mst_edges_s5_exceptions/files/testcase.py`, class "
    "`TestPrimNaNEdge`, single test method `test_prim_maximum_hits_nan`). "
    "During this test the generator function "
    "`networkx.algorithms.tree.mst.prim_mst_edges` (defined in "
    "`networkx/algorithms/tree/mst.py`) is iterated over the seeded random "
    "graph built by `build_graph()`, and an exception is raised inside the "
    "generator's own frame by one of its `raise` statements and propagates "
    "out of it to the test. Report that exception. "
    "Answer as a JSON object with exactly two string keys: "
    "`exception_type` and `exception_message`. "
    "`exception_type` naming convention: use the bare `type(exc).__name__` for "
    "built-in exceptions (e.g. `KeyError`, never `builtins.KeyError`), and "
    "`module.QualName` for any non-built-in exception (e.g. "
    "`networkx.exception.NetworkXError`). "
    "`exception_message` is exactly `str(exc)` of the raised exception object, "
    "character for character (including any punctuation, spacing, and the "
    "Python reprs of any values interpolated into it), as a plain JSON string "
    "with no added quotes or prefix."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_exc(rest):
    if not rest.startswith("exc="):
        fail(f"malformed exception event: {rest[:200]}")
    body = rest[len("exc="):]
    idx = body.rfind(" locals={")
    if idx < 0:
        fail("cannot locate locals in exception event")
    body = body[:idx]
    name, sep, exc_repr = body.partition(": ")
    if not sep:
        fail(f"cannot split exception name/repr: {body[:200]}")
    if exc_repr.endswith("..."):
        fail("exception repr was truncated by tracer")
    try:
        node = ast.parse(exc_repr, mode="eval").body
    except SyntaxError as e:
        fail(f"cannot parse exception repr {exc_repr!r}: {e}")
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == name and not node.keywords):
        fail(f"unexpected exception repr shape: {exc_repr!r}")
    args = [ast.literal_eval(a) for a in node.args]
    if len(args) == 0:
        message = ""
    elif len(args) == 1:
        message = str(args[0])
    else:
        message = str(tuple(args))
    bobj = getattr(builtins, name, None)
    if not (isinstance(bobj, type) and issubclass(bobj, BaseException)):
        fail(f"non-builtin exception {name!r}: module unknown from trace")
    return name, message


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    events = []
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_FILE):
            continue
        events.append(m)
    if not events:
        fail("no events for target function in trace")

    exc_events = [m for m in events if m.group("event") == "exception"]
    if not exc_events:
        fail("no exception events in target frame")
    parsed = {parse_exc(m.group("rest")) for m in exc_events}
    if len(parsed) != 1:
        fail(f"expected exactly one distinct exception, got {sorted(parsed)}")
    # The raise must be the last thing the frame does: final event is a return.
    if events[-1].group("event") != "return":
        fail("target frame did not terminate after exception")
    exc_type, exc_message = parsed.pop()

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": {"exception_message": exc_message, "exception_type": exc_type},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))
    print(f"target events: {len(events)}; exception events: {len(exc_events)}")


if __name__ == "__main__":
    main()
