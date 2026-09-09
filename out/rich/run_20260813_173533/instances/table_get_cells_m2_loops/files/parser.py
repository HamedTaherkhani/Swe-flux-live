#!/usr/bin/env python3
"""Parse trace log for M2_Loops oracle (max/min loop iterations across invocations)."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_FILE = "rich/table.py"
TARGET_FUNC = "rich.table.Table._get_cells"
TARGET_FUNC_SUFFIX = "Table._get_cells"
LOOP_HEADER_LINE = 676
DEF_LINE = 627
TEST_CLASS = "TestTableGetCellsLoopDynamics"
TEST_FILE = "rich_qa/table_get_cells_m2_loops/files/testcase.py"

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

QUESTION = (
    f"Consider pytest tests in `{TEST_FILE}::{TEST_CLASS}` (all `test_*` methods "
    "in that class, executed in pytest's default collection order). The answer "
    "aggregates behavior across every test method in the class during one full "
    "pytest run of the class.\n\n"
    f"Target function: `{TARGET_FUNC}` in `{TARGET_FILE}`.\n\n"
    "Invocation counting: an invocation is one logical execution of the target, "
    "numbered chronologically from 1. Because `_get_cells` is a generator (it "
    "uses `yield`), CPython's trace machinery emits a `return` event at each "
    "`yield` and a new `call` event when the generator resumes at the yield "
    "line; treat the first `call` on line 627 of `rich/table.py` through the "
    "final `return` for that qualname before the next `call` on line 627 as a "
    "single invocation, ignoring those internal suspend/resume boundaries.\n\n"
    f"Loop: the `for` loop whose header is on line {LOOP_HEADER_LINE} of "
    f"`{TARGET_FILE}` (`for cell in column.cells:`). Iteration counting is "
    "1-based: iteration N is the Nth time the loop body's first statement "
    "executes. The body-first statement is the initial statement in the loop "
    "body block (not the `for` header line); use its 1-based line number as it "
    "appears in the repository file.\n\n"
    "For each invocation, count how many iterations that loop executes (line "
    "events at the body-first line while inside that invocation). Across all "
    "invocations in the run, report:\n"
    "- `max_iterations`: the largest per-invocation iteration count (integer)\n"
    "- `min_iterations`: the smallest per-invocation iteration count (integer)\n\n"
    "Tie-breaking: if multiple invocations share the same max or min count, "
    "the reported integer is still that shared count (no invocation index is "
    "emitted)."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC or func.endswith(TARGET_FUNC_SUFFIX)


def _load_loop_body_first_line(repo_root: Path) -> int:
    source = (repo_root / TARGET_FILE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and node.lineno == LOOP_HEADER_LINE:
            if not node.body:
                raise SystemExit(f"Loop at {LOOP_HEADER_LINE} has empty body")
            return node.body[0].lineno
    raise SystemExit(
        f"Could not locate for-loop header at line {LOOP_HEADER_LINE} in {TARGET_FILE}"
    )


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
        if TARGET_FILE not in m.group("file").replace("\\", "/"):
            continue
        func = m.group("func")
        if not _func_matches(func):
            continue
        events.append(
            {
                "lineno": int(m.group("lineno")),
                "func": func,
                "event": m.group("event"),
            }
        )
    return events


def _logical_invocations(events: list[dict]) -> list[list[dict]]:
    invocations: list[list[dict]] = []
    current: list[dict] = []
    for ev in events:
        if ev["event"] == "call" and ev["lineno"] == DEF_LINE:
            if current:
                invocations.append(current)
            current = [ev]
            continue
        if current:
            current.append(ev)
    if current:
        invocations.append(current)
    return invocations


def _invocation_iteration_counts(events: list[dict], body_line: int) -> list[int]:
    counts: list[int] = []
    for inv_events in _logical_invocations(events):
        count = sum(
            1
            for ev in inv_events
            if ev["event"] == "line" and ev["lineno"] == body_line
        )
        counts.append(count)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default="/testbed")
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    body_line = _load_loop_body_first_line(repo_root)

    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    per_invocation = _invocation_iteration_counts(events, body_line)
    if not per_invocation:
        raise SystemExit("No invocations found in trace for target function")
    if any(count == 0 for count in per_invocation):
        raise SystemExit(
            "Zero iterations detected for at least one invocation; "
            f"body line {body_line}"
        )

    oracle_answer = {
        "max_iterations": max(per_invocation),
        "min_iterations": min(per_invocation),
    }
    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
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
