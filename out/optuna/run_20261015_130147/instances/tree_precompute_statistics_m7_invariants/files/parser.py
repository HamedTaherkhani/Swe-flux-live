"""Derive the M7 invariant report for _FanovaTree._precompute_statistics from a trace log."""

from __future__ import annotations

import argparse
import json
import re
import sys

import numpy as np


TARGET_QUALNAME = "optuna.importance._fanova._tree._FanovaTree._precompute_statistics"
TARGET_FILE = "optuna/importance/_fanova/_tree.py"
ENTRY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>\w+) (?P<rest>.*)$",
    re.S,
)
EVAL_NS = {"np": np, "array": np.array, "nan": np.nan, "inf": np.inf, "__builtins__": {"abs": abs, "min": min, "max": max, "len": len}}

# (predicate text, observation line or "exception", needed locals)
PREDICATES = [
    ("value >= 0.0", 160, ("value",)),
    ("weight > 0.0", 160, ("weight",)),
    ("child_node_index == node_index + 1", 166, ("child_node_index", "node_index")),
    ("child_node_index > node_index", 166, ("child_node_index", "node_index")),
    ("abs(child_values[0] - child_values[1]) < 1.5", 179, ("child_values",)),
    ("weight <= n_nodes", "exception", ("weight", "n_nodes")),
]


QUESTION = """\
Test file: optuna_qa/tree_precompute_statistics_m7_invariants/files/testcase.py, test class `TestPrecomputeStatistics`. Run ALL test methods of that class (every `test_*` method, e.g. pytest id `optuna_qa/tree_precompute_statistics_m7_invariants/files/testcase.py::TestPrecomputeStatistics::<method>`); the answer aggregates over every one of them. Target function: `optuna.importance._fanova._tree._FanovaTree._precompute_statistics` in `optuna/importance/_fanova/_tree.py` (def on line 144). An invocation is one call of this function during the test run; every invocation (including several in one test method) contributes.

Each candidate predicate below is a Python expression over the target frame's local variables, attached to one observation point. A line observation point "line N" means: every time line N (absolute, 1-based line number in `optuna/importance/_fanova/_tree.py`) is about to execute inside the target function's own frame, evaluate the predicate on the local variable values at that moment (i.e. after all earlier statements ran, before line N itself runs). The observation point "exception" means: every time an exception is raised or propagates through the target function's own frame (one evaluation per such event, using the locals at that moment). Evaluate with ordinary Python semantics on the actual runtime objects (numpy scalars compare as numbers; `abs` is the builtin). Frames of other functions (callees, comprehensions) are never observation points.

Candidate predicates (copy each predicate string verbatim, character for character):
1. `value >= 0.0` -- observed at line 160
2. `weight > 0.0` -- observed at line 160
3. `child_node_index == node_index + 1` -- observed at line 166
4. `child_node_index > node_index` -- observed at line 166
5. `abs(child_values[0] - child_values[1]) < 1.5` -- observed at line 179
6. `weight <= n_nodes` -- observed at "exception"

For each predicate report: `predicate` (the exact predicate string above, without backticks or the "observed at" part), `observations` (int: total number of evaluations summed over all invocations in all test methods), `violations` (int: how many of those evaluations were false), and `held_always` (bool: true iff observations > 0 and violations == 0). A predicate whose observation point is never reached is reported with observations 0, violations 0, held_always false.

Answer as JSON: {"invariant_report": [{"held_always": bool, "observations": int, "predicate": str, "violations": int}, ...]} with exactly one entry per candidate predicate, sorted by `predicate` ascending by plain Python string comparison (code-point order; predicates are unique so no tie-break is needed). Booleans are JSON `true`/`false`; counts are JSON integers.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def read_entries(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        fail(f"trace log not found: {path}")
    if not raw.strip():
        fail(f"trace log is empty: {path}")
    # Multi-line reprs span several physical lines; split on timestamp-prefixed lines.
    chunks = re.split(r"\n(?=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )", raw)
    entries = []
    for chunk in chunks:
        m = ENTRY_RE.match(chunk.strip("\n"))
        if not m or m.group("func") != TARGET_QUALNAME:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        rest = m.group("rest")
        idx = rest.rfind("locals=")
        locals_repr = eval(rest[idx + len("locals="):], {"__builtins__": {}}) if idx >= 0 else {}
        entries.append(
            {"line": int(m.group("line")), "event": m.group("event"), "locals": locals_repr}
        )
    return entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    entries = read_entries(args.trace_log)
    if not entries:
        fail("no events for the target function in the trace log")
    n_calls = sum(1 for e in entries if e["event"] == "call")
    if n_calls == 0:
        fail("no call events for the target function")

    tallies = {p: [0, 0] for p, _, _ in PREDICATES}
    state: dict[str, str] = {}
    for e in entries:
        if e["event"] == "call":
            state = {}
        state.update(e["locals"])
        point = "exception" if e["event"] == "exception" else (
            e["line"] if e["event"] == "line" else None
        )
        if point is None:
            continue
        for pred, where, names in PREDICATES:
            if where != point:
                continue
            env = dict(EVAL_NS)
            for n in names:
                if n not in state:
                    fail(f"local {n!r} unavailable at {point} for predicate {pred!r}")
                env[n] = eval(state[n], EVAL_NS)
            ok = bool(eval(pred, env))
            tallies[pred][0] += 1
            tallies[pred][1] += 0 if ok else 1

    report = []
    for pred in sorted(tallies):
        obs, vio = tallies[pred]
        report.append(
            {
                "held_always": obs > 0 and vio == 0,
                "observations": obs,
                "predicate": pred,
                "violations": vio,
            }
        )
    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))
    print(f"invocations={n_calls} events={len(entries)}")


if __name__ == "__main__":
    main()
