#!/usr/bin/env python
"""Derive the M7_Invariants oracle for optuna.cli._dump_table from a trace log."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys


TARGET_FILE = "optuna/cli.py"
TARGET_FUNC = "optuna.cli._dump_table"
TEST_FILE = "optuna_qa/cli_dump_table_m7_invariants/files/testcase.py"
TEST_CLASS = "TestDumpTableThroughCli"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) ")
ENUM_RE = re.compile(r"^<ValueType\.(\w+): \d+>$")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_enum(raw: str) -> str:
    m = ENUM_RE.match(raw)
    if not m:
        fail(f"cannot parse ValueType repr {raw!r}")
    return m.group(1)


def parse_literal(raw: str):
    if raw.endswith("..."):
        fail(f"truncated local value encountered: {raw[:80]!r}")
    return ast.literal_eval(raw)


# Each predicate: (text, observation line, evaluator over reconstructed locals).
def _p_t_not_none(s):
    return parse_enum(s["t"]) != "NONE"


def _p_vt_numeric(s):
    return parse_enum(s["value_type"]) == "NUMERIC"


def _p_width_eq_header(s):
    header = parse_literal(s["header"])
    return int(s["max_width"]) == len(header[int(s["column"])])


def _p_header_sep_len(s):
    return len(parse_literal(s["header_string"])) == len(parse_literal(s["separator"]))


def _p_width_lt(s):
    return int(s["max_width"]) < 61


def _p_column_zero(s):
    return int(s["column"]) == 0


PREDICATES = [
    ("t != ValueType.NONE", 219, _p_t_not_none),
    ("value_type == ValueType.NUMERIC", 219, _p_vt_numeric),
    ("max_width == len(header[column])", 225, _p_width_eq_header),
    ("len(header_string) == len(separator)", 225, _p_header_sep_len),
    ("max_width < 61", 225, _p_width_lt),
    ("column == 0", 222, _p_column_zero),
]


def build_question() -> str:
    pred_lines = "\n".join(
        f'  - predicate string "{text}" -- observed at every `line` event of line {line} of '
        f"{TARGET_FILE}"
        for text, line, _ in sorted(PREDICATES, key=lambda p: p[0])
    )
    return (
        f"Run the pytest class `{TEST_FILE}::{TEST_CLASS}` (all 12 test methods; their execution "
        f"order does not matter because the answer AGGREGATES totals over ALL of them). The test methods never "
        f"call the target directly: they drive the Optuna CLI (`optuna.cli.main`) with "
        f"`-f table`, which reaches `optuna.cli._dump_table` (file `{TARGET_FILE}`) via "
        f"`optuna.cli._format_output`. Consider every invocation of `optuna.cli._dump_table` "
        f"during the run (an invocation = one call of the function).\n\n"
        f"For each candidate predicate below, evaluate it as a Python expression over the local "
        f"variables of the `_dump_table` frame at the stated observation point. An observation "
        f"point 'line N' means: each time line N of `{TARGET_FILE}` (absolute, 1-based line "
        f"numbers of the file as it exists in the repository) is about to execute inside "
        f"`_dump_table` -- i.e. the locals are those BEFORE the statement on line N runs. Each "
        f"such execution counts as exactly one observation (across all invocations and all "
        f"test methods). `ValueType` is `optuna.cli.ValueType`; enum comparison is by member "
        f"identity.\n"
        f"{pred_lines}\n\n"
        f"For each predicate report: `predicate` (the predicate string exactly as written above, "
        f"without the surrounding quotes), `observations` (int: total number of times its "
        f"observation line executed inside `_dump_table`), `violations` (int: how many of those "
        f"evaluations were False), and `held_always` (bool: true iff `violations == 0` AND "
        f"`observations > 0`; a predicate whose observation line is never executed is reported "
        f"as `observations: 0, violations: 0, held_always: false`).\n\n"
        f'Answer as a JSON object {{"invariant_report": [...]}} with exactly one entry per '
        f"predicate (6 entries), each having exactly the keys `held_always`, `observations`, "
        f"`predicate`, `violations`. Sort the list by the `predicate` string ascending using "
        f"plain Python string ordering (code-point order; predicate strings are unique so there "
        f"are no ties). Use JSON booleans `true`/`false` and JSON integers."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw_lines = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not raw_lines:
        fail("trace log is empty")

    obs = {text: 0 for text, _, _ in PREDICATES}
    viol = {text: 0 for text, _, _ in PREDICATES}
    by_line: dict[int, list] = {}
    for p in PREDICATES:
        by_line.setdefault(p[1], []).append(p)

    state: dict[str, str] | None = None
    n_events = 0
    n_calls = 0
    for ln in raw_lines:
        m = LINE_RE.match(ln)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        n_events += 1
        event = m.group("event")
        idx = ln.rfind(" locals={")
        if idx < 0:
            fail(f"no locals in trace line: {ln[:120]}")
        diff = ast.literal_eval(ln[idx + len(" locals="):])
        if event == "call":
            n_calls += 1
            state = dict(diff)
            continue
        if state is None:
            fail("event before any call")
        if event == "return":
            state = None
            continue
        state.update(diff)
        if event != "line":
            continue
        lineno = int(m.group("lineno"))
        for text, _, fn in by_line.get(lineno, []):
            obs[text] += 1
            if not fn(state):
                viol[text] += 1

    if n_events == 0 or n_calls == 0:
        fail(f"no events for {TARGET_FUNC} in trace")

    report = [
        {
            "held_always": obs[text] > 0 and viol[text] == 0,
            "observations": obs[text],
            "predicate": text,
            "violations": viol[text],
        }
        for text in sorted(obs)
    ]
    oracle = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str",
                 "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
