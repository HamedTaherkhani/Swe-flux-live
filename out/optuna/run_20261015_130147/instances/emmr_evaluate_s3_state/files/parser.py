#!/usr/bin/env python
"""Trace -> oracle.json for emmr_evaluate_s3_state (S3_ProgramState)."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_REL = "optuna/terminator/improvement/emmr.py"
MODULE = "optuna.terminator.improvement.emmr"
CLASS_NAME = "EMMREvaluator"
FUNC_NAME = "evaluate"
TARGET_QUALNAME = f"{MODULE}.{CLASS_NAME}.{FUNC_NAME}"
TEST_FILE = "optuna_qa/emmr_evaluate_s3_state/files/testcase.py"
TEST_CLASS = "TestEMMREvaluateState"
TEST_METHOD = "test_evaluate_over_growing_histories"
OBS_TARGET = "theta_t1_star"
OBS_OCCURRENCE = 2
VARIABLES = sorted(
    [
        "len_trials",
        "score_vals",
        "sign",
        "standarized_score_vals",
        "theta_t1_star",
        "theta_t1_star_index",
        "theta_t_star",
        "theta_t_star_index",
    ]
)

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_obs_line(src_path: Path) -> int:
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == CLASS_NAME), None
    )
    if cls is None:
        fail(f"class {CLASS_NAME} not found")
    func = next(
        (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == FUNC_NAME), None
    )
    if func is None:
        fail(f"{CLASS_NAME}.{FUNC_NAME} not found")
    hits = [
        n.lineno
        for n in ast.walk(func)
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == OBS_TARGET
    ]
    if len(hits) != 1:
        fail(f"expected exactly one assignment to {OBS_TARGET}, found {len(hits)}")
    return hits[0]


def parse_records(text: str) -> list[tuple[int, str, dict]]:
    records = []
    lines = text.split("\n")
    # Locals reprs may contain real newlines; re-join continuation lines.
    buf = None
    joined = []
    for raw in lines:
        if re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ", raw):
            if buf is not None:
                joined.append(buf)
            buf = raw
        elif buf is not None:
            buf += "\n" + raw
    if buf is not None:
        joined.append(buf)
    for rec in joined:
        m = LINE_RE.match(rec.replace("\n", "\x00"))
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        loc = ast.literal_eval(m.group("locals").replace("\x00", "\n"))
        records.append((int(m.group("lineno")), m.group("event"), loc))
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace_path}")

    src_path = Path.cwd() / TARGET_REL
    if not src_path.is_file():
        src_path = Path(__file__).resolve().parents[3] / TARGET_REL
    obs_line = find_obs_line(src_path)

    records = parse_records(trace_path.read_text(encoding="utf-8"))
    if not records:
        fail("zero trace events for the target function")

    state: dict = {}
    hits = 0
    pending = False
    snapshot = None
    n_calls = 0
    for lineno, event, loc in records:
        if event == "call":
            n_calls += 1
            state = dict(loc)
            pending = False
            continue
        if pending:
            # Locals at the next event of the same frame reflect state after obs_line ran.
            state.update(loc)
            snapshot = dict(state)
            break
        state.update(loc)
        if event == "line" and lineno == obs_line:
            hits += 1
            if hits == OBS_OCCURRENCE:
                pending = True
    if snapshot is None:
        fail(f"line {obs_line} did not execute {OBS_OCCURRENCE} times (seen {hits})")

    observed = []
    for var in VARIABLES:
        if var not in snapshot:
            fail(f"variable {var} not bound at observation point")
        val = snapshot[var]
        if val.endswith("..."):
            fail(f"repr of {var} truncated by tracer")
        observed.append({"value": val, "variable": var})

    var_list = ", ".join(f"`{v}`" for v in VARIABLES)
    question = (
        f"Consider the test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}` (the only test "
        f"method of class `{TEST_CLASS}` in `{TEST_FILE}`). During this test run, the method "
        f"`{TARGET_QUALNAME}` (defined in `{TARGET_REL}`) is invoked several times. "
        f"Line {obs_line} of `{TARGET_REL}` (absolute, 1-based line number in the file as it "
        f"exists in the repository) is the statement `{OBS_TARGET} = "
        f"normalized_params[theta_t1_star_index, :]`. Count executions of that line across "
        f"ALL invocations of `{CLASS_NAME}.{FUNC_NAME}` during the test in chronological order "
        f"(invocations that return before reaching it contribute no executions). Observe the "
        f"local variables of the `{FUNC_NAME}` frame immediately after line {obs_line} has "
        f"finished executing for the {OBS_OCCURRENCE}nd time (i.e. before any later line of "
        f"that invocation runs). Report the values of exactly these local variables: "
        f"{var_list}.\n\n"
        "Answer format: a JSON object `{\"observed_state\": [...]}` whose list contains one "
        "object per variable with exactly the keys `\"variable\"` (the bare local variable "
        "name as a string) and `\"value\"` (a string). The list is sorted by variable name in "
        "ascending Python string order (so underscores and letters compare by code point; "
        "e.g. `a_b` sorts before `ab`). Each `value` is the Python `repr()` of the variable's "
        "value at that moment, exactly as produced by `repr()` in this environment (with "
        "NumPy's default print options). Containers and NumPy arrays are the `repr` of the "
        "whole object, e.g. `array([0.5, 1. ])`; NumPy scalars keep their NumPy repr, e.g. "
        "`np.float64(2.5)`, while built-in ints are plain, e.g. `7`. If a repr spans several "
        "lines, the JSON string contains the real newline characters and the original "
        "spacing/indentation verbatim. Do not round, reformat, or strip any value."
    )

    template = {"observed_state": [{"value": "str", "variable": "str"}]}
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": template,
        "oracle_answer": {"observed_state": observed},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    print(f"invocations={n_calls} obs_line={obs_line} target_events={len(records)}")


if __name__ == "__main__":
    main()
