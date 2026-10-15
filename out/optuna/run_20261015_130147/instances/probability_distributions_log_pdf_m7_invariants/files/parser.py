#!/usr/bin/env python
"""Trace -> oracle.json for probability_distributions_log_pdf_m7_invariants."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/samplers/_tpe/probability_distributions.py"
TARGET_FUNC = (
    "optuna.samplers._tpe.probability_distributions._MixtureOfProductDistribution.log_pdf"
)
TEST_PATH = "optuna_qa/probability_distributions_log_pdf_m7_invariants/files/testcase.py"
TEST_CLASS = "TestMixtureLogPdfInvariants"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) ")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_lines(src_path: str) -> dict[str, int]:
    with open(src_path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_MixtureOfProductDistribution":
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == "log_pdf":
                    func = sub
    if func is None:
        fail("log_pdf not found in target source")
    lines = source.splitlines()
    wanted = {
        "loop_head": "if isinstance(d, _BatchedCategoricalDistributions):",
        "walrus": "if (step := d.step) == 0.0:",
        "append_cont": "cont_dists.append(d)",
        "disc_first": "xi_uniq, xi_inv = np.unique(x[:, i], return_inverse=True)",
    }
    out = {}
    for key, text in wanted.items():
        hits = [
            n
            for n in range(func.lineno, func.end_lineno + 1)
            if lines[n - 1].strip().startswith(text)
        ]
        if len(hits) != 1:
            fail(f"could not uniquely locate {key!r}: {hits}")
        out[key] = hits[0]
    return out


def parse_locals(line: str) -> dict:
    idx = line.find(" locals={")
    if idx < 0:
        return {}
    try:
        return ast.literal_eval(line[idx + len(" locals=") :])
    except Exception as exc:  # pragma: no cover
        fail(f"cannot parse locals in line: {line[:200]!r} ({exc})")
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        fail("trace log is empty")

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    src_path = os.path.join(root, TARGET_REL)
    if not os.path.isfile(src_path):
        src_path = os.path.join(os.getcwd(), TARGET_REL)
    L = find_lines(src_path)

    preds = {
        "i == len(cont_dists)": [0, 0],
        "i <= 7": [0, 0],
        "step >= 0.2": [0, 0],
        "not is_log": [0, 0],
        "step < 1.0": [0, 0],
        "step <= d.low": [0, 0],
    }

    def record(name: str, ok: bool) -> None:
        preds[name][0] += 1
        if not ok:
            preds[name][1] += 1

    n_events = 0
    n_calls = 0
    state: dict | None = None
    n_cont = 0
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        n_events += 1
        event = m.group("event")
        lineno = int(m.group("lineno"))
        loc = parse_locals(line)
        if event == "call":
            n_calls += 1
            state = dict(loc)
            n_cont = 0
            continue
        if state is None:
            fail("event outside of a call")
        if event in ("return", "exception"):
            state = None if event == "return" else state
            continue
        state.update(loc)
        if event != "line":
            continue
        if lineno == L["loop_head"]:
            record("i == len(cont_dists)", int(state["i"]) == n_cont)
        elif lineno == L["walrus"]:
            is_log = state["is_log"]
            if is_log not in ("True", "False"):
                fail(f"unexpected is_log repr {is_log!r}")
            record("not is_log", is_log == "False")
            record("i <= 7", int(state["i"]) <= 7)
        elif lineno == L["append_cont"]:
            n_cont += 1
        elif lineno == L["disc_first"]:
            step = float(state["step"])
            record("step < 1.0", step < 1.0)
            record("step >= 0.2", step >= 0.2)
            d_repr = state["d"]
            if d_repr.startswith("_BatchedDiscreteTruncLogNormDistributions("):
                mlow = re.search(r"\blow=([-+0-9.eE]+)", d_repr)
                if not mlow:
                    fail("cannot read d.low from truncated repr")
                record("step <= d.low", step <= float(mlow.group(1)))

    if n_events == 0 or n_calls == 0:
        fail("no events for the target function in the trace")

    report = [
        {
            "held_always": v[1] == 0 and v[0] > 0,
            "observations": v[0],
            "predicate": k,
            "violations": v[1],
        }
        for k, v in sorted(preds.items())
    ]

    question = f"""Test file: `{TEST_PATH}`, test class `{TEST_CLASS}`. Run the WHOLE class with pytest (all of its `test_...` methods; the answer aggregates over ALL of them — counts are totals summed across every method and every invocation, regardless of test order).

Target function: `{TARGET_FUNC}` (method `_MixtureOfProductDistribution.log_pdf` in `{TARGET_REL}`). An "invocation" is one call of this method during the run (1-based, chronological); all invocations from all test methods count, including those made by helper methods of the test class. Calls to `sample` and other functions are irrelevant except as they shape the inputs.

Each candidate predicate below is evaluated on the local variables of the `log_pdf` frame at a specific observation point. An observation point is "the moment just before the given source line executes" (i.e. each time execution reaches that line, before its statement runs), using the code as it exists in the repository. `len(cont_dists)` means the length of that list at that moment in the current invocation (it starts empty in every invocation); `i` and `d` are the current loop variables. Each arrival at the observation point (with its extra condition, if any, satisfied) is one observation.

Candidate predicates (copy the predicate strings exactly as written between backticks):
1. `i == len(cont_dists)` — observed at line {L['loop_head']} (`if isinstance(d, _BatchedCategoricalDistributions):`, first line of the `for i, d in enumerate(self.distributions)` loop body), once per loop iteration.
2. `not is_log` — observed at line {L['walrus']} (`if (step := d.step) == 0.0:`); `is_log` is the value assigned on the preceding line in the same iteration.
3. `i <= 7` — observed at line {L['walrus']} as well (same observations as predicate 2, evaluated independently).
4. `step < 1.0` — observed at line {L['disc_first']} (`xi_uniq, xi_inv = np.unique(x[:, i], return_inverse=True)`, discrete branch); `step` is the value bound by the walrus on line {L['walrus']} in the same iteration (compare the Python float exactly, no rounding).
5. `step >= 0.2` — observed at line {L['disc_first']} as well (same observations as predicate 4, evaluated independently, exact float comparison).
6. `step <= d.low` — observed at line {L['disc_first']} as well, but ONLY in iterations where `d` is an instance of `_BatchedDiscreteTruncLogNormDistributions` (in other iterations reaching that line it is not observed at all).

For each predicate report: `observations` = total number of observations (int); `violations` = how many of those observations had the predicate evaluate to False (int); `held_always` = true iff `violations == 0` AND `observations > 0`. A predicate that is never observed must be reported as `observations: 0`, `violations: 0`, `held_always: false`.

Answer format: a JSON object `{{"invariant_report": [...]}}` whose list holds exactly one object per candidate predicate (6 entries), each with keys `held_always` (JSON boolean true/false), `observations` (int), `predicate` (the exact predicate string, e.g. an entry for a hypothetical predicate `a > b` would have `"predicate": "a > b"`), `violations` (int). Sort the list by the `predicate` string ascending using plain Python string ordering (codepoint order); predicate strings are all distinct so no tie-break is needed."""

    oracle = {
        "question_kind": "M7_Invariants",
        "question": question,
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))
    print(f"invocations={n_calls} events={n_events}")


if __name__ == "__main__":
    main()
