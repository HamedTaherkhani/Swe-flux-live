#!/usr/bin/env python
"""Trace -> oracle.json for rank_get_rank_info_s6_calls (S6_InterProceduralCFG)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_REL = "optuna/visualization/_rank.py"
UTILS_REL = "optuna/visualization/_utils.py"
TARGET_QUALNAME = "optuna.visualization._rank._get_rank_info"
INVOCATION = 2
TEST_FILE = "optuna_qa/rank_get_rank_info_s6_calls/files/testcase.py"
TEST_CLASS = "TestRankPlotTwoStudies"
TEST_METHOD = "test_plot_rank_on_two_studies"

TRACKED = {
    TARGET_QUALNAME: TARGET_REL,
    "optuna.visualization._rank._get_rank_info.<locals>.target": TARGET_REL,
    "optuna.visualization._rank._get_order_with_same_order_averaging": TARGET_REL,
    "optuna.visualization._rank._convert_color_idxs_to_scaled_rgb_colors": TARGET_REL,
    "optuna.visualization._rank._get_rank_subplot_info": TARGET_REL,
    "optuna.visualization._rank._get_axis_info": TARGET_REL,
    "optuna.visualization._utils._check_plot_args": UTILS_REL,
    "optuna.visualization._utils._is_numerical": UTILS_REL,
    "optuna.visualization._utils._is_log_scale": UTILS_REL,
}

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

_tracked_list = "\n".join(
    f"  - `{name}` (in `{TRACKED[name]}`)" for name in sorted(TRACKED) if name != TARGET_QUALNAME
)

QUESTION = f"""\
Run the single test method `{TEST_METHOD}` of the test class `{TEST_CLASS}` in the file `{TEST_FILE}` (pytest id `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}`). The test calls the public `optuna.visualization.plot_rank` twice, which internally calls the function `{TARGET_QUALNAME}` defined in `{TARGET_REL}`.

An invocation of `{TARGET_QUALNAME}` is one Python `call` event of that function (its body starting to execute in a new frame); invocations are numbered 1-based in chronological order over the whole test run. Focus on invocation number {INVOCATION}.

Tracked functions (exactly this set, and nothing else):
{_tracked_list}
The nested function `target` is the closure defined inside `_get_rank_info` (its qualname contains `<locals>`). Calls to anything else are NOT tracked and do not appear — in particular not lambdas or other callables defined in the test file, not `plot_rank`, not functions of other modules (study/trial/numpy/plotly code), not builtins, and not generator-expression or list/set/dict-comprehension frames (on the Python 3.11 interpreter used here comprehensions run in their own `<listcomp>`/`<setcomp>`/`<genexpr>` frames; those are ignored even when they live inside a tracked function). `{TARGET_QUALNAME}` itself is NOT included in the answer (its own call event that starts invocation {INVOCATION} is not listed).

Report the ordered sequence of `call` events of tracked functions that occur while invocation {INVOCATION} of `{TARGET_QUALNAME}` is on the call stack — i.e. after that invocation starts and before it returns. Include transitive calls, not just direct ones: a tracked function called by another tracked function (or by any untracked code) during that window counts as well. Every call event is a separate element: repeated calls of the same function are all listed, in chronological order, with no deduplication or collapsing. None of the tracked functions is a generator, so there are no resumptions to consider.

Answer format: a JSON object `{{"function_call_order": [...]}}` whose list elements are objects `{{"file": <str>, "func": <str>}}` in chronological call order:
- `file`: repo-relative path of the file defining the called function, forward slashes, no leading `./` (e.g. `optuna/visualization/_utils.py`).
- `func`: dotted name `<module>.<qualname>` exactly as Python's `co_qualname` gives it, prefixed by the module's `__name__`; e.g. a module-level function `foo` in module `pkg.mod` is `pkg.mod.foo`, and a function `inner` nested in function `outer` of that module is `pkg.mod.outer.<locals>.inner`.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log not found: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    depth = 0  # nesting depth of the target frames (no recursion expected)
    active = False
    sequence: list[dict[str, str]] = []
    finished = False

    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        func = m.group("func")
        event = m.group("event")
        if func not in TRACKED:
            continue
        path = m.group("file").replace("\\", "/")
        rel = TRACKED[func]
        if not path.endswith("/" + rel):
            fail(f"unexpected file for {func}: {path}")
        if func == TARGET_QUALNAME:
            target_events += 1
            if event == "call":
                if depth == 0:
                    invocation += 1
                    if invocation == INVOCATION:
                        active = True
                depth += 1
                continue
            if event == "return":
                depth -= 1
                if depth == 0 and active:
                    active = False
                    finished = True
                continue
            continue
        if active and event == "call":
            sequence.append({"file": rel, "func": func})

    if target_events == 0:
        fail(f"no trace events for {TARGET_QUALNAME}")
    if invocation < INVOCATION:
        fail(f"only {invocation} invocations of target found")
    if not finished:
        fail("target invocation did not return within the trace")
    if not sequence:
        fail("empty call sequence")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": sequence},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={invocation} sequence_len={len(sequence)}")


if __name__ == "__main__":
    main()
