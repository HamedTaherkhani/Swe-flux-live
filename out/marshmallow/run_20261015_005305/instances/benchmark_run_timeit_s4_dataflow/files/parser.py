#!/usr/bin/env python
"""Harvest observed def-use pairs of run_timeit's locals from the trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "performance/benchmark.py"
TARGET_QUAL = "performance.benchmark.run_timeit"
LAMBDA_QUAL = "performance.benchmark.run_timeit.<locals>.<lambda>"
TEST_PATH = "marshmallow_qa/benchmark_run_timeit_s4_dataflow/files/testcase.py"
TEST_CLASS = "BenchmarkMainTest"
TEST_METHOD = "test_main_degenerate_runs"
TRACKED = ["best", "iterations", "profile", "quotes", "quotes_schema", "repeat"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: exc=(?P<exc>.*?))?(?: retval=.*?)? locals=(?P<locals>\{.*\})\s*$"
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_source_info(repo_root):
    src_path = repo_root / TARGET_REL
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_timeit"),
        None,
    )
    if func is None:
        die("run_timeit not found in source")
    params = [a.arg for a in func.args.args + func.args.kwonlyargs]
    lambdas = [n for n in ast.walk(func) if isinstance(n, ast.Lambda)]
    lambda_ids = set()
    lambda_reads = {}
    for lam in lambdas:
        for n in ast.walk(lam.body):
            lambda_ids.add(id(n))
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in TRACKED:
                lambda_reads.setdefault(n.lineno, []).append((n.col_offset, n.id))
    # reads made by run_timeit's own frame, per physical line, in source order
    frame_reads = {}
    assign_lines = {}
    for n in ast.walk(func):
        if id(n) in lambda_ids:
            continue
        if isinstance(n, ast.Name) and n.id in TRACKED:
            if isinstance(n.ctx, ast.Load):
                frame_reads.setdefault(n.lineno, []).append((n.col_offset, n.id))
            elif isinstance(n.ctx, ast.Store):
                assign_lines.setdefault(n.id, set()).add(n.lineno)
    for d in (frame_reads, lambda_reads):
        for k in d:
            d[k] = [name for _, name in sorted(d[k])]
    return func.lineno, params, frame_reads, lambda_reads, assign_lines


def parse_events(trace_path):
    if not trace_path.exists():
        die(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        die(f"trace log empty: {trace_path}")
    events = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        func = m.group("func")
        if func not in (TARGET_QUAL, LAMBDA_QUAL):
            continue
        try:
            locs = ast.literal_eval(m.group("locals"))
        except Exception:
            locs = {}
        events.append(
            {
                "line": int(m.group("line")),
                "func": func,
                "event": m.group("event"),
                "exc": m.group("exc"),
                "locals": locs,
            }
        )
    if not any(e["func"] == TARGET_QUAL and e["event"] == "call" for e in events):
        die("no call events for run_timeit in trace")
    return events


def truncate_reads(line, reads, state_locals):
    """Reads actually evaluated on a line whose evaluation raised."""
    if line == 104:
        # best * 1e6 / iterations / len(quotes): left-to-right evaluation
        it = state_locals.get("iterations")
        if it is None:
            die("iterations value unknown at line 104 exception")
        if float(ast.literal_eval(it)) == 0:
            return reads[: reads.index("iterations") + 1]
        return reads
    if not reads:
        return reads
    die(f"unsupported exception at line {line} with tracked reads {reads}")


def compute(events, def_line, params, frame_reads, lambda_reads, assign_lines):
    pairs = set()
    invocations = 0
    depth = 0
    cur_defs = None
    cur_locals = None
    last_line = None
    pending_reads = None  # (line, reads) not yet committed for current frame line
    for ev in events:
        if ev["func"] == TARGET_QUAL:
            kind = ev["event"]
            if kind == "call":
                if cur_defs is not None:
                    die("nested run_timeit invocation not supported")
                invocations += 1
                cur_defs = {p: def_line for p in params}
                cur_locals = dict(ev["locals"])
                last_line = None
                pending_reads = None
                continue
            if cur_defs is None:
                die("event outside invocation")
            if kind == "exception":
                if pending_reads is None or pending_reads[0] != ev["line"]:
                    die("exception without preceding line event")
                pending_reads = (
                    ev["line"],
                    truncate_reads(ev["line"], pending_reads[1], cur_locals),
                )
            # reads of the previously executed line happen before any rebinding
            if pending_reads is not None:
                ln, reads = pending_reads
                for name in reads:
                    pairs.add((name, cur_defs[name], ln))
                pending_reads = None
            if kind != "return":
                # names whose value changed since the previous event were rebound
                # by the most recently executed assignment line
                for name in sorted(ev["locals"]):
                    if name not in TRACKED:
                        continue
                    if last_line not in assign_lines.get(name, set()):
                        die(f"cannot attribute def of {name} at line {ev['line']}")
                    cur_defs[name] = last_line
                cur_locals.update(ev["locals"])
            if kind == "line":
                last_line = ev["line"]
                pending_reads = (ev["line"], list(frame_reads.get(ev["line"], [])))
            elif kind == "exception":
                pending_reads = None
            elif kind == "return":
                cur_defs = None
                cur_locals = None
        else:  # lambda frame
            if cur_defs is None:
                die("lambda event outside run_timeit invocation")
            if ev["event"] == "line":
                for name in lambda_reads.get(ev["line"], []):
                    pairs.add((name, cur_defs[name], ev["line"]))
    if invocations == 0:
        die("zero run_timeit invocations")
    return invocations, sorted(pairs)


QUESTION = """Test: `marshmallow_qa/benchmark_run_timeit_s4_dataflow/files/testcase.py`, test class `BenchmarkMainTest`, test method `test_main_degenerate_runs` (pytest id `marshmallow_qa/benchmark_run_timeit_s4_dataflow/files/testcase.py::BenchmarkMainTest::test_main_degenerate_runs`; it is the only test method in the class), run with pytest from the repository root under the container's CPython 3.11 interpreter.

Target function: `performance.benchmark.run_timeit`, defined in `performance/benchmark.py` (the `def` is at line 85; the test reaches it only through `performance.benchmark.main`).

Question: across ALL invocations of `run_timeit` during this test (an invocation = one call of the function, i.e. one new frame of `run_timeit`), which def-use pairs are actually observed at runtime for the six tracked local variables `best`, `iterations`, `profile`, `quotes`, `quotes_schema`, `repeat`?

Definitions:
- A "def" of a variable is a binding of it. Parameters (`quotes`, `iterations`, `repeat`, `profile`) are defined at the `def` line (85) when the invocation starts. An assignment statement defines its target at the line where the assignment statement begins (for a multi-line assignment, its first line). A def only takes effect if the assignment actually completes (if the right-hand side raises, no new def happens).
- A "use" is a read of the variable's value that is actually evaluated at runtime. The use line is the physical source line on which the variable name token appears (for a multi-line call, each argument's own line, not the statement's first line). Sub-expressions that are never evaluated (e.g. a branch body that is not entered, or the remainder of an expression after an operation in it raised an exception, following Python's left-to-right evaluation order) produce NO use. Assignment targets are not uses; there is no augmented assignment, loop or comprehension in this function.
- The `lambda` at line 94 is part of `run_timeit`: merely creating the lambda object is NOT a use of `quotes_schema` or `quotes`; a use at line 94 occurs only when the lambda's body is actually executed (each execution reads the closure variables `quotes_schema` and `quotes`, whose reaching defs are the ones current in the enclosing invocation).
- A def-use pair (variable, def_line, use_line) is observed when, in some invocation, the value bound at def_line is read at use_line before the variable is rebound in that invocation. Pairs never cross invocations.
- Global names, attributes, builtins and keyword-argument names (e.g. `number=`) are not tracked variables; only the six names above count.

Output: a JSON object `{"observed_def_use_pairs": [...]}`, where each element is `{"def_line": int, "use_line": int, "variable": str}` (variable is the bare local name, e.g. "x"; line numbers are absolute 1-based line numbers in `performance/benchmark.py` as JSON integers). Include each distinct (variable, def_line, use_line) triple exactly once (deduplicated across all invocations). A tracked variable for which no pair is observed simply contributes no elements. Sort ascending by `variable` (plain string order), then by `def_line`, then by `use_line`."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    if not (repo_root / TARGET_REL).exists():
        repo_root = Path.cwd()
    def_line, params, frame_reads, lambda_reads, assign_lines = load_source_info(repo_root)
    events = parse_events(Path(args.trace_log))
    invocations, pairs = compute(
        events, def_line, params, frame_reads, lambda_reads, assign_lines
    )
    if not pairs:
        die("no def-use pairs computed")
    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for v, d, u in pairs
        ]
    }
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
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"invocations={invocations} pairs={len(pairs)}")
    for v, d, u in pairs:
        print(f"  {v}: {d} -> {u}")


if __name__ == "__main__":
    main()
