"""Derive the M7 oracle (per-predicate invariant report) for louvain._one_level from the trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/algorithms/community/louvain.py"
FUNC_NAME = "_one_level"
QUALNAME = f"networkx.algorithms.community.louvain.{FUNC_NAME}"
TEST_PATH = "networkx_qa/louvain_one_level_m7_invariants/files/testcase.py"
TEST_CLASS = "TestLouvainScenarios"

# (predicate expression, observation line)
PREDICATES = [
    ("best_com == u_com", 320),
    ("gain != remove_cost", 320),
    ("degree >= 2", 330),
    ("best_gain > 0", 336),
    ("nb_moves < 28", 336),
    ("x >= 0", 312),
]
assert len({p for p, _ in PREDICATES}) == len(PREDICATES)

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) "
)

_pred_lines = "\n".join(
    f"  - `{p}` — observed at line {ln}" for p, ln in PREDICATES
)

QUESTION = f"""\
Test: `{TEST_PATH}`, class `{TEST_CLASS}`. The answer aggregates over ALL test methods of this class (every `test_*` method, i.e. every pytest id of the form `{TEST_PATH}::{TEST_CLASS}::<method>`), run together in one pytest session. Counts are totals summed across all of them.

Target function: the module-level function `{FUNC_NAME}` in `{REL_FILE}` (dotted name `{QUALNAME}`). The tests never call it directly; it is reached through the public Louvain entry points. Every invocation (one call of the target = one new frame), however it is reached, contributes.

Candidate predicates. Each is a Python expression over the target's own local variables, evaluated with the values those locals hold at the observation point. The observation point of a predicate is: every time execution reaches the stated line of `{REL_FILE}` (absolute, 1-based line number in the file as it exists in the repository), evaluated just BEFORE that line's statement executes (i.e. with the locals as they are when control arrives at that line; for an `if` line, before its condition is evaluated). Each arrival at the line is one observation, so a line inside a loop yields one observation per loop iteration in which it is reached:
{_pred_lines}

Question: for each candidate predicate, over the whole test class, how many times was it observed, how many of those observations evaluated to False, and did it hold at every observation?

Answer format: JSON object `{{"invariant_report": [...]}}` with exactly one element per candidate predicate above (6 elements). Each element is an object with exactly the keys:
  - `predicate` (str): the predicate expression copied verbatim from the backticks above (e.g. a predicate written `a < b` is reported as "a < b"; the line number is not part of the string);
  - `observations` (int): the number of observations as defined above, summed over all invocations in all test methods;
  - `violations` (int): how many of those observations evaluated to False;
  - `held_always` (bool): true iff `observations > 0` and `violations == 0`. A predicate whose observation line is never reached is reported as `observations: 0`, `violations: 0`, `held_always: false`.
Sort the list ascending by `predicate` using plain Python string ordering (code-point order); predicate strings are all distinct, so no tie-break is needed.
"""

TEMPLATE = {
    "invariant_report": [
        {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
    ]
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_value(s):
    try:
        return ast.literal_eval(s)
    except Exception:
        fail(f"cannot parse traced value {s!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file() or path.stat().st_size == 0:
        fail(f"trace log missing or empty: {path}")

    stats = {p: [0, 0] for p, _ in PREDICATES}
    by_line = {}
    for p, ln in PREDICATES:
        by_line.setdefault(ln, []).append(p)

    state = None
    n_calls = 0
    n_events = 0
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m.group("file").endswith(REL_FILE) or m.group("func") != QUALNAME:
                continue
            n_events += 1
            event = m.group("event")
            idx = raw.find(" locals=")
            if idx < 0:
                fail(f"no locals in trace line: {raw[:200]}")
            changed = ast.literal_eval(raw[idx + len(" locals="):].strip())
            if event == "call":
                n_calls += 1
                state = {}
            if state is None:
                fail("event before call in trace")
            state.update(changed)
            if event == "line":
                line = int(m.group("line"))
                for p in by_line.get(line, ()):
                    names = {
                        n.id for n in ast.walk(ast.parse(p, mode="eval"))
                        if isinstance(n, ast.Name)
                    }
                    env = {}
                    for n in names:
                        if n not in state:
                            fail(f"local {n} unavailable at line {line}")
                        env[n] = parse_value(state[n])
                    stats[p][0] += 1
                    if not eval(p, {"__builtins__": {}}, env):
                        stats[p][1] += 1
            elif event in ("return", "exception"):
                if event == "return":
                    state = None

    if n_events == 0 or n_calls == 0:
        fail("no events for the target function in trace")

    report = []
    for p in sorted(stats):
        obs, vio = stats[p]
        report.append(
            {
                "held_always": obs > 0 and vio == 0,
                "observations": obs,
                "predicate": p,
                "violations": vio,
            }
        )

    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": {"invariant_report": report},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={n_calls} events={n_events}")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
