"""Derive the S6 (inter-procedural call order) oracle for GPSampler._sample_relative_impl."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


REPO_FILE = "optuna/samplers/_gp/sampler.py"
MODULE = "optuna.samplers._gp.sampler"
TARGET = f"{MODULE}.GPSampler._sample_relative_impl"
TRACKED = {
    TARGET,
    f"{MODULE}._standardize_values",
    f"{MODULE}._get_params",
    f"{MODULE}._get_constraint_vals_and_feasibility",
    f"{MODULE}.GPSampler._get_constraints_acqf_args",
    f"{MODULE}.GPSampler._get_best_params_for_multi_objective",
    f"{MODULE}.GPSampler._optimize_acqf",
}
TEST_ID = (
    "optuna_qa/sampler_sample_relative_impl_s6_calls/files/testcase.py::"
    "TestGPSamplerPendingConstrainedFlow::test_pending_constrained_multiobjective"
)

EVENT_RE = re.compile(r" (?P<file>/\S+\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Consider the pytest test `{TEST_ID}` (file `optuna_qa/sampler_sample_relative_impl_s6_calls/files/testcase.py`, class `TestGPSamplerPendingConstrainedFlow`, single test method `test_pending_constrained_multiobjective`), run once from the repository root.

The target function is `GPSampler._sample_relative_impl` in `{REPO_FILE}` (qualname `{TARGET}`). The test never calls it directly; it is reached through `study.ask()` / `trial.suggest_*` -> `GPSampler.sample_relative`.

Tracked functions (exactly these seven, all defined in `{REPO_FILE}`; any other function, method, builtin, lambda, comprehension frame, or code in other files is NOT tracked):
  1. `{TARGET}` (the target itself)
  2. `{MODULE}._standardize_values`
  3. `{MODULE}._get_params`
  4. `{MODULE}._get_constraint_vals_and_feasibility`
  5. `{MODULE}.GPSampler._get_constraints_acqf_args`
  6. `{MODULE}.GPSampler._get_best_params_for_multi_objective`
  7. `{MODULE}.GPSampler._optimize_acqf`

A "call" is the start of a new Python frame executing one of these functions (one entry per actual invocation; none of them are generators, so there are no resumptions). Inclusion rule: record every call of a tracked function that starts while SOME invocation of the target is on the call stack -- i.e. transitive/nested calls count, not only calls made directly from the target's own frame (for example a call made from inside a list comprehension inside the target, or from inside another tracked function, counts) -- PLUS the call of the target itself each time it is invoked (so every target invocation contributes one target entry, followed by the tracked calls that happen during it). Calls of tracked functions that happen while no target invocation is on the stack (e.g. `_get_params` called from `GPSampler.sample_relative` before it calls the target) are excluded. Every call is listed separately (no deduplication), across ALL invocations of the target during the test, in chronological order of when each call starts.

Report this as `function_call_order`: a JSON list of objects `{{"file": ..., "func": ...}}` in chronological order, where `file` is the repo-relative path of the file defining the function (e.g. `optuna/samplers/_gp/sampler.py`) and `func` is the dotted `module.qualname` of the called function, e.g. `optuna.samplers._gp.sampler.GPSampler.sample_independent` for a method or `optuna.samplers._gp.sampler._some_helper` for a module-level function (no `<locals>`, no argument lists)."""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        fail("trace log is empty")

    events = []
    for raw in lines:
        m = EVENT_RE.search(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REPO_FILE):
            continue
        events.append((m.group("func"), m.group("event")))

    if not any(f == TARGET and e == "call" for f, e in events):
        fail("no call events for the target function in the trace")

    depth = 0
    order = []
    for func, event in events:
        if func == TARGET and event == "call":
            depth += 1
            order.append({"file": REPO_FILE, "func": func})
            continue
        if func == TARGET and event == "return":
            depth -= 1
            if depth < 0:
                fail("unbalanced target return event")
            continue
        if event == "call" and func in TRACKED and depth > 0:
            order.append({"file": REPO_FILE, "func": func})

    if depth != 0:
        fail("target invocation never returned")
    if len(order) < 2:
        fail("suspiciously short call order")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": order},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    n_target = sum(1 for o in order if o["func"] == TARGET)
    print(f"target invocations: {n_target}; call order length: {len(order)}")


if __name__ == "__main__":
    main()
