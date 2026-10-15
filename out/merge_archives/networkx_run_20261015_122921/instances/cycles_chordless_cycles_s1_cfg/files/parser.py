#!/usr/bin/env python
"""Trace -> oracle.json for cycles_chordless_cycles_s1_cfg."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] if "networkx_qa" in Path(__file__).resolve().parts else Path("/testbed")
TARGET_REL = "networkx/algorithms/cycles.py"
TARGET_FUNC_NAME = "chordless_cycles"
TARGET_QUALNAME = "networkx.algorithms.cycles.chordless_cycles"
TEST_PATH = "networkx_qa/cycles_chordless_cycles_s1_cfg/files/testcase.py"
TEST_CLASS = "TestChordlessCyclesPaths"
TEST_METHOD = "test_chordless_cycles_batch"
TARGET_INVOCATION = 3

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def first_code_line(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC_NAME:
            lines = [node.lineno] + [d.lineno for d in node.decorator_list]
            return min(lines)
    fail(f"function {TARGET_FUNC_NAME} not found in {source_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file():
        fail(f"trace log missing: {trace}")
    text = trace.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log empty: {trace}")

    start_line = first_code_line(REPO_ROOT / TARGET_REL)

    invocations = []
    current = None
    n_events = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m["file"].replace("\\", "/").endswith(TARGET_REL):
            continue
        if m["func"] != TARGET_QUALNAME:
            continue
        n_events += 1
        event = m["event"]
        line = int(m["line"])
        if event == "call" and line == start_line:
            # a fresh generator frame starts (resumptions report other lines)
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("line event before first call event")
            current.append(line)

    if n_events == 0:
        fail(f"no events for {TARGET_QUALNAME} in trace")
    if len(invocations) < TARGET_INVOCATION:
        fail(f"only {len(invocations)} invocations found, need {TARGET_INVOCATION}")

    path = invocations[TARGET_INVOCATION - 1]
    if not path:
        fail("target invocation has no line events")

    executed_path = [
        {"file": TARGET_REL, "func": TARGET_QUALNAME, "line": ln} for ln in path
    ]

    question = QUESTION
    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": question,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {"executed_path": executed_path},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations found: {len(invocations)}")
    print(f"target invocation {TARGET_INVOCATION}: {len(path)} line events, "
          f"{len(set(path))} distinct lines")


QUESTION = (
    "Run the single pytest test "
    "`networkx_qa/cycles_chordless_cycles_s1_cfg/files/testcase.py::TestChordlessCyclesPaths::test_chordless_cycles_batch` "
    "(test class `TestChordlessCyclesPaths`, only test method `test_chordless_cycles_batch`) on the Python 3.12 "
    "interpreter of this environment. Consider the target generator function "
    "`networkx.algorithms.cycles.chordless_cycles`, defined in `networkx/algorithms/cycles.py` (decorated with "
    "`@nx._dispatchable`). Every time the test calls `chordless_cycles(...)` and iterates the resulting generator, "
    "a new frame of this function is created; number these invocations 1, 2, 3, ... in the chronological order in "
    "which their frames START executing during the test (generator resumptions after a `yield` do NOT start a new "
    "invocation; they continue the same one). The test consumes each generator completely with `list(...)` before "
    "creating the next, including the calls made inside the final assertion. "
    "Question: for invocation 3, what is the exact ordered sequence of executed source lines of the "
    "`chordless_cycles` frame itself, from its first executed line until that generator is exhausted? "
    "Counting rules: the sequence is exactly the chronological list of `line` events that `sys.settrace` reports "
    "for that frame (i.e. events whose `frame` is the `chordless_cycles` frame), concatenated across all of its "
    "resumptions, with every repetition kept (no deduplication), including repeated events of loop headers each "
    "time they are re-evaluated. Do NOT include `call`, `return` or `exception` events, and do NOT include lines "
    "executed in other frames: the nested function `stems`, the generator expressions created inside "
    "`chordless_cycles` (these run in their own frames), `_chordless_cycle_search`, `_NeighborhoodCache`, or any "
    "networkx/library function called from the body are all excluded. List comprehensions are inlined into the "
    "enclosing frame on Python 3.12, so the line events they emit (possibly several consecutive events on the same "
    "line) ARE part of the sequence. When a generator is resumed after a `yield`/`yield from`, record whatever "
    "`line` events `sys.settrace` reports next; do not insert an extra entry for the resumed line unless such a "
    "`line` event is actually reported. The decorator line and the `def` line never appear (they produce no line "
    "event for this frame), and the docstring produces no line event. Every other statement in the body fits on "
    "one line; in general a statement is reported at the line where it begins. Line numbers are absolute, 1-based "
    "line numbers in `networkx/algorithms/cycles.py` as it exists in this repository. "
    "Answer format: a JSON object `{\"executed_path\": [...]}` whose list has one object per line event, in "
    "chronological order, each with exactly the keys `file` (string, always the repo-relative path "
    "`networkx/algorithms/cycles.py`), `func` (string, always the dotted module.qualname "
    "`networkx.algorithms.cycles.chordless_cycles`) and `line` (JSON integer, not a string), e.g. "
    "`{\"file\": \"networkx/algorithms/cycles.py\", \"func\": \"networkx.algorithms.cycles.chordless_cycles\", "
    "\"line\": 1}` (illustrative line value only)."
)

if __name__ == "__main__":
    main()
