#!/usr/bin/env python3
"""Parse trace log for S3_ProgramState oracle (locals at a precise observation point)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TARGET_FILE = "rich/table.py"
TARGET_FUNC = "rich.table.Table._calculate_column_widths"
TARGET_FUNC_SUFFIX = "Table._calculate_column_widths"
DEF_LINE = 523
OBSERVATION_LINE = 552
OBSERVATION_EXECUTION = 14
TEST_FILE = (
    "rich_qa/table_calculate_column_widths_s3_state/files/testcase.py"
)
TEST_CLASS = "TestTableCalculateColumnWidthsState"
TEST_METHOD = "test_programmatic_width_solver_scenario"
VARIABLES = (
    "fixed_widths",
    "flex_widths",
    "flexible_width",
    "index",
    "widths",
)

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?: locals=(?P<locals>\{.*\}))?"
)

LOCALS_PAIR_RE = re.compile(r"'([^']+)': '((?:\\'|[^'])*)'")

QUESTION = (
    f"For pytest test `{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}`, consider the "
    f"single direct call to `{TARGET_FUNC}` in `{TARGET_FILE}` that the test "
    "makes (the call whose result is bound to `widths` in the test method).\n\n"
    "Line execution counting: within that call, use 1-based source line "
    f"numbers from `{TARGET_FILE}` as checked into the repository. The k-th "
    "execution of line L is the k-th time the interpreter begins executing "
    "source line L during that call. Each loop iteration that reaches line L "
    "counts separately. For multi-line statements elsewhere in the function, "
    "the executed line is where the statement begins; the observation line is "
    "a single-line statement. The `def` line and docstring lines are not "
    "counted as body executions.\n\n"
    f"Observation point: immediately after line {OBSERVATION_LINE} of "
    f"`{TARGET_FILE}` has finished executing for the {OBSERVATION_EXECUTION}-th "
    "time during that call (line 552 is `if column.flexible:` inside the "
    "`for index, column in enumerate(columns):` loop).\n\n"
    "At that instant, read the live local variables in the "
    "`_calculate_column_widths` stack frame. Report these names: "
    + ", ".join(f"`{name}`" for name in VARIABLES)
    + ".\n\n"
    "Value serialization: each reported value is the Python `repr()` string of "
    "the variable's runtime object (for example an integer becomes `\"7\"`, a "
    "list of ints becomes `\"[1, 2, 3]\"` with no spaces after commas). "
    "Containers are the `repr()` of the whole container, not per-element "
    "strings. Use JSON string values, so Python `None`/`True`/`False` would "
    "appear as `\"None\"`/`\"True\"`/`\"False\"` inside strings if they "
    "occurred.\n\n"
    "Return JSON with top-level key `observed_state`: a list of objects, each "
    "with keys `variable` (the variable name) and `value` (its repr string), "
    "sorted by `variable` ascending (ASCII/Unicode code-point order)."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC or func.endswith(TARGET_FUNC_SUFFIX)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.find(TARGET_FILE)
    if idx == -1:
        return normalized
    return normalized[idx:]


def _parse_locals_dict(raw: str) -> dict[str, str]:
    return {
        key: value.replace("\\'", "'")
        for key, value in LOCALS_PAIR_RE.findall(raw)
    }


def _parse_trace(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log empty: {path}")

    events: list[dict] = []
    for raw in text.splitlines():
        m = TRACE_RE.match(raw)
        if not m:
            continue
        file_path = _normalize_file(m.group("file"))
        if file_path != TARGET_FILE:
            continue
        func = m.group("func")
        if not _func_matches(func):
            continue
        events.append(
            {
                "lineno": int(m.group("lineno")),
                "func": func,
                "event": m.group("event"),
                "locals": _parse_locals_dict(m.group("locals") or "{}"),
            }
        )
    return events


def _first_invocation(events: list[dict]) -> list[dict]:
    inv: list[dict] = []
    started = False
    for ev in events:
        if ev["event"] == "call" and ev["lineno"] == DEF_LINE:
            if started:
                raise SystemExit(
                    "Expected exactly one invocation of target function"
                )
            started = True
            inv = [ev]
            continue
        if started:
            inv.append(ev)
            if ev["event"] == "return":
                break
    if not started:
        raise SystemExit("No invocation found for target function")
    if inv[-1]["event"] != "return":
        raise SystemExit("Invocation missing return event")
    return inv


def _observed_state(invocation: list[dict]) -> dict[str, str]:
    state: dict[str, str] = {}
    line_count = 0
    for ev in invocation:
        if ev["event"] == "call":
            state = {}
            continue
        if ev["event"] != "line":
            continue
        state.update(ev["locals"])
        if ev["lineno"] == OBSERVATION_LINE:
            line_count += 1
            if line_count == OBSERVATION_EXECUTION:
                missing = [name for name in VARIABLES if name not in state]
                if missing:
                    raise SystemExit(
                        "Variables missing at observation point: "
                        + ", ".join(missing)
                    )
                return {name: state[name] for name in VARIABLES}
    raise SystemExit(
        f"Observation point line {OBSERVATION_LINE} execution "
        f"{OBSERVATION_EXECUTION} not reached (saw {line_count})"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    invocation = _first_invocation(events)
    values = _observed_state(invocation)
    observed_state = [
        {"variable": name, "value": values[name]} for name in sorted(VARIABLES)
    ]

    oracle_answer = {"observed_state": observed_state}
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
