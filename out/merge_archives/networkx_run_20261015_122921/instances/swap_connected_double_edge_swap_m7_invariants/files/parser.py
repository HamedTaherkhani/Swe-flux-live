"""Derive the M7_Invariants oracle for swap.connected_double_edge_swap from the trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FUNC = "networkx.algorithms.swap.connected_double_edge_swap"
TARGET_FILE = "networkx/algorithms/swap.py"

# (predicate string, observation line, evaluator over the reconstructed locals)
PREDICATES = [
    ("line 305: nswap > 0", 305, lambda s: s["nswap"] > 0),
    ("line 339: u < x", 339, lambda s: s["u"] < s["x"]),
    ("line 352: window == 1", 352, lambda s: s["window"] == 1),
    ("line 360: window <= 2", 360, lambda s: s["window"] <= 2),
    ("line 390: swapcount <= n", 390, lambda s: s["swapcount"] <= s["n"]),
    ("line 405: window < 7", 405, lambda s: s["window"] < 7),
]

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) "
    r"(?:retval=.*? )?(?:exc=.*? )?locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the pytest test class `TestConnectedDoubleEdgeSwapInvariants` in the file "
    "`networkx_qa/swap_connected_double_edge_swap_m7_invariants/files/testcase.py`. "
    "The answer aggregates over ALL 13 `test_*` methods of that class (pytest ids "
    "`networkx_qa/swap_connected_double_edge_swap_m7_invariants/files/testcase.py::"
    "TestConnectedDoubleEdgeSwapInvariants::<method>`), run together in one pytest "
    "session in file order. Target function: "
    "`networkx.algorithms.swap.connected_double_edge_swap`, defined in "
    "`networkx/algorithms/swap.py` (lines 232-406 of the repository file as it exists; "
    "line numbers below are absolute and 1-based in that file). An invocation is one "
    "call of this function's own frame (1-based, chronological); all invocations "
    "count, including one that raises. "
    "Each candidate predicate below is written as `line L: <Python expression>`. "
    "Its observation point is the line event of line L in the target function's own "
    "frame, i.e. the moment immediately BEFORE line L executes; every time line L is "
    "about to execute counts as one observation (a line inside a loop is observed "
    "once per execution). The expression is evaluated on the values the function's "
    "local variables hold at that moment (before line L's own effects; e.g. at a "
    "`n += 1` line, `n` still has its old value). Observations are summed over all "
    "invocations and all test methods. The candidate predicates, verbatim:\n"
    + "".join(f"  - `{p}`\n" for p, _, _ in PREDICATES)
    + "(For reference: line 305 is `raise nx.NetworkXError(\"Graph has fewer than four "
    "nodes.\")`; 339 is the `if x not in G[u] and y not in G[v]:` in the small-window "
    "branch; 352 is the first undo statement `G.add_edge(u, v)` of the small-window "
    "`else:` branch; 360 is `window = math.ceil(window / 2)` in the small-window branch "
    "(under `if fail:`); 390 is `n += 1` in the large-window branch; 405 is "
    "`window = math.ceil(window / 2)` after the large-window undo loop.) "
    "For each predicate report: `predicate` = the predicate string exactly as listed "
    "above (including the `line L: ` prefix, without backticks); `observations` = the "
    "number of observations (JSON integer); `violations` = how many of those "
    "observations evaluated to false (JSON integer); `held_always` = JSON boolean, "
    "true iff `violations == 0` AND `observations > 0`. A predicate whose line is "
    "never reached must still be reported, with `observations: 0`, `violations: 0`, "
    "`held_always: false`. "
    "Answer as a JSON object with exactly one key, `invariant_report`, whose value is "
    "a list with one object per predicate (keys `held_always`, `observations`, "
    "`predicate`, `violations`), sorted by `predicate` ascending by plain string "
    "comparison (the strings are unique, so no tie-break is needed). Example of one "
    "entry's shape: {\"held_always\": false, \"observations\": 4, \"predicate\": "
    "\"line 1: a < b\", \"violations\": 3}."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        fail(f"trace log empty: {path}")

    obs = {p: 0 for p, _, _ in PREDICATES}
    vio = {p: 0 for p, _, _ in PREDICATES}
    n_events = 0
    n_calls = 0
    state = None
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC or not m.group("file").endswith(TARGET_FILE):
            continue
        n_events += 1
        event = m.group("event")
        loc = {k: parse_value(v) for k, v in ast.literal_eval(m.group("locals")).items()}
        if event == "call":
            n_calls += 1
            state = dict(loc)
            continue
        if state is None:
            fail("event before any call event")
        state.update(loc)
        if event != "line":
            continue
        lineno = int(m.group("line"))
        for pred, pline, fn in PREDICATES:
            if pline == lineno:
                obs[pred] += 1
                if not fn(state):
                    vio[pred] += 1

    if n_events == 0 or n_calls == 0:
        fail("no events for target function in trace")

    report = [
        {
            "held_always": obs[p] > 0 and vio[p] == 0,
            "observations": obs[p],
            "predicate": p,
            "violations": vio[p],
        }
        for p in sorted(obs)
    ]
    out = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
