#!/usr/bin/env python3
"""Parse trace log into M7_Invariants oracle for rich.cells._cell_len."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Callable

TARGET_FILE = "rich/cells.py"
TARGET_FUNC = "rich.cells._cell_len"

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)

PREDICATE_SPECS: list[tuple[str, int, Callable[[dict[str, Any]], bool]]] = [
    (
        "character in SPECIAL",
        156,
        lambda bindings: bindings["character"] in bindings["SPECIAL"],
    ),
    (
        "character_count == len(text)",
        156,
        lambda bindings: bindings["character_count"] == len(bindings["text"]),
    ),
    (
        "index == 0",
        131,
        lambda bindings: bindings["index"] == 0,
    ),
    (
        "index >= total_width",
        156,
        lambda bindings: bindings["index"] >= bindings["total_width"],
    ),
    (
        "total_width != 70",
        158,
        lambda bindings: bindings["total_width"] != 70,
    ),
    (
        "total_width >= 0",
        156,
        lambda bindings: bindings["total_width"] >= 0,
    ),
]


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_local_value(name: str, raw: str) -> Any:
    if name == "cell_table":
        return raw
    return ast.literal_eval(raw)


def _parse_locals(raw: str) -> dict[str, Any]:
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"locals is not a dict: {raw!r}")
    return {
        str(key): _parse_local_value(str(key), str(value))
        for key, value in parsed.items()
    }


def _parse_trace_events(trace_log: Path) -> list[dict[str, Any]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    events: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        if TARGET_FUNC not in raw_line:
            continue
        match = LINE_EVENT_RE.match(raw_line)
        if not match:
            continue
        file_path = _normalize_path(match.group("file"))
        if file_path != TARGET_FILE:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append(
            {
                "lineno": int(match.group("lineno")),
                "event": match.group("event"),
                "locals": _parse_locals(match.group("locals")),
            }
        )

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )
    return events


def _evaluate_predicate(
    bindings: dict[str, Any], predicate: Callable[[dict[str, Any]], bool]
) -> bool:
    try:
        return bool(predicate(bindings))
    except (KeyError, TypeError, ValueError):
        return False


def _compute_invariant_report(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {
        predicate: {"observations": 0, "violations": 0}
        for predicate, _, _ in PREDICATE_SPECS
    }

    bindings: dict[str, Any] = {}
    active = False

    for event in events:
        event_type = str(event["event"])
        if event_type == "call":
            active = True
            bindings = dict(event["locals"])
            continue
        if event_type == "return":
            active = False
            bindings = {}
            continue
        if not active or event_type != "line":
            continue

        bindings.update(event["locals"])
        lineno = int(event["lineno"])

        for predicate, observation_line, predicate_fn in PREDICATE_SPECS:
            if lineno != observation_line:
                continue
            stats[predicate]["observations"] += 1
            if not _evaluate_predicate(bindings, predicate_fn):
                stats[predicate]["violations"] += 1

    report: list[dict[str, Any]] = []
    for predicate, _, _ in PREDICATE_SPECS:
        observations = stats[predicate]["observations"]
        violations = stats[predicate]["violations"]
        report.append(
            {
                "predicate": predicate,
                "held_always": violations == 0 and observations > 0,
                "observations": observations,
                "violations": violations,
            }
        )

    report.sort(key=lambda item: str(item["predicate"]))
    return report


QUESTION = """\
During pytest run of \
rich_qa/cells_cell_len_m7_invariants/files/testcase.py::TestCellLenInvariants, \
consider every invocation of rich.cells._cell_len in rich/cells.py (source lines \
113-158) reached during ALL test methods in that class. The test never calls \
_cell_len directly; it reaches the function indirectly through rich.cells.set_cell_size \
(which calls cell_len, which in turn calls _cell_len for non-single-cell-width text) \
and rich.text.Text.truncate (which calls set_cell_size when cropping wide text). \
Invocation order is chronological across the entire pytest session in alphabetical \
order by test method name within the class (for example \
test_alternating_joiner_runs before test_crop_via_text_truncate).

Every test input is built programmatically from seeded generators and always \
contains at least one of the zero-width joiner U+200D or variation selector-16 \
U+FE0F, so every invocation that reaches _cell_len executes the while-loop path \
(lines 144-156) and never executes the early-return comprehension path at lines \
131-133.

Line numbers are 1-based positions in rich/cells.py as checked into the repository. \
For multi-line statements, a line event corresponds to the line where that \
statement begins. Docstring lines inside _cell_len are never observation points.

At each observation point below, evaluate the candidate predicates on the full \
local variable bindings in effect in the _cell_len stack frame immediately before \
that source line begins executing (standard Python frame locals at the line event). \
Parameters text and unicode_version are defined on entry. Locals introduced later \
remain bound until reassigned or the invocation returns. The walrus-assigned name \
character_width is present only after line 153 executes in the current loop iteration; \
if it is absent when a predicate mentions it, treat the reference as an evaluation \
error and count the observation as a violation.

Predicate literals use Python semantics: None is the null object; strings are \
compared by value; SPECIAL is the local set defined at line 139; character and \
last_measured_character are single-codepoint str values or None.

Report invariant_report: a JSON list with one object per candidate predicate below. \
Each object has exactly these keys:

- predicate (str): the predicate text, copied verbatim from the list below
- held_always (bool): true iff observations > 0 and violations == 0; false if \
observations == 0 or violations > 0
- observations (int): how many times the predicate was evaluated at its observation \
point (summed across all invocations and all test methods)
- violations (int): how many of those evaluations were false (or evaluation errors)

Sort invariant_report ascending by predicate string; break ties by the order listed \
below.

Candidate predicates and observation points (each predicate is evaluated only at its \
own observation point):

1. Predicate "character in SPECIAL" — observation point: each time source line 156 \
(index += 1) is about to execute inside the while loop.
2. Predicate "character_count == len(text)" — observation point: line 156 before \
execution.
3. Predicate "index == 0" — observation point: each time source line 131 (the return \
sum(...) statement in the no-joiner/no-variation-selector branch) is about to \
execute.
4. Predicate "index >= total_width" — observation point: line 156 before execution.
5. Predicate "total_width != 70" — observation point: each time source line 158 \
(return total_width) is about to execute after the while loop completes.
6. Predicate "total_width >= 0" — observation point: line 156 before execution.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)

    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 60:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 60"
        )
    distinct_lines = {int(event["lineno"]) for event in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )
    line_counts: dict[int, int] = {}
    for event in line_events:
        lineno = int(event["lineno"])
        line_counts[lineno] = line_counts.get(lineno, 0) + 1
    if max(line_counts.values()) < 20:
        raise SystemExit("No executed line reached at least 20 trace events")

    invariant_report = _compute_invariant_report(events)
    violation_counts = {item["violations"] for item in invariant_report}
    if len(violation_counts) < 2:
        raise SystemExit("Invariant violations are not varied enough")

    oracle_answer = {"invariant_report": invariant_report}
    template_answer = {
        "invariant_report": [
            {
                "held_always": "bool",
                "observations": "int",
                "predicate": "str",
                "violations": "int",
            }
        ]
    }

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
