#!/usr/bin/env python3
"""Parse trace logs for Optimizer.generic_visit interprocedural call order."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/optimizer.py"
TARGET_FUNC = "jinja2.optimizer.Optimizer.generic_visit"
TARGET_INVOCATION = 13

TRACKED_FUNCTIONS = (
    "jinja2.optimizer.Optimizer.generic_visit",
    "jinja2.visitor.NodeTransformer.generic_visit",
    "jinja2.visitor.NodeVisitor.visit",
)

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _repo_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = "src/jinja2/"
    idx = normalized.find(marker)
    if idx >= 0:
        return normalized[idx:]
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    raise SystemExit(f"Could not make repo-relative path from trace entry: {path}")


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def harvest_function_call_order(trace_log: Path, invocation: int) -> list[dict[str, str]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    tracked = set(TRACKED_FUNCTIONS)
    target_events = 0
    invocation_counter = 0
    active_invocations: list[int] = []
    sequence: list[dict[str, str]] = []

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue

        func = parsed["func"]
        event = parsed["event"]

        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                invocation_counter += 1
                active_invocations.append(invocation_counter)
            elif event == "return":
                if active_invocations:
                    active_invocations.pop()

        if event != "call" or func not in tracked:
            continue

        if invocation not in active_invocations:
            continue

        sequence.append(
            {
                "file": _repo_relative_path(parsed["path"]),
                "func": func,
            }
        )

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if invocation_counter < invocation:
        raise SystemExit(
            f"Trace contains only {invocation_counter} invocations of {TARGET_FUNC}, "
            f"but invocation {invocation} was requested"
        )

    if not sequence:
        raise SystemExit(
            f"No tracked call events found during invocation {invocation} of {TARGET_FUNC}"
        )

    return sequence


def build_question() -> str:
    tracked_list = ", ".join(f"`{name}`" for name in TRACKED_FUNCTIONS)
    return (
        "Consider the single test method "
        "`jinja_qa/optimizer_generic_visit_s6_calls/files/testcase.py::"
        "TestOptimizerGenericVisitCallOrder::"
        "test_optimizer_generic_visit_interprocedural_calls`.\n\n"
        "That test calls `Optimizer.generic_visit` **directly** on expression "
        f"nodes from parsed templates (see `{TARGET_FILE}`).\n\n"
        "Target function: `jinja2.optimizer.Optimizer.generic_visit` "
        f"(the method whose `def` begins at line 31 of `{TARGET_FILE}`).\n\n"
        "**Function identity format**: each function is written as "
        "`module.qualname` using the defining module and `co_qualname`, for "
        "example `jinja2.visitor.NodeVisitor.visit`.\n\n"
        "**Invocation numbering**: an invocation of the target is one `call` "
        f"event for `{TARGET_FUNC}` during the test run, numbered in "
        "chronological order starting at 1.\n\n"
        f"**Tracked functions** (only these three): {tracked_list}.\n\n"
        "**Inclusion rule for call events**: build the ordered sequence of "
        "`call` events whose callee is one of the tracked functions above and "
        f"that occur while invocation {TARGET_INVOCATION} of "
        f"`{TARGET_FUNC}` is on the Python call stack (the target frame has "
        "been entered by its `call` event and not yet left by its matching "
        "`return` event). Include nested and transitive calls to tracked "
        "functions made while that invocation is active, including calls "
        "from child invocations of the target that run before invocation "
        f"{TARGET_INVOCATION} returns. Include every matching `call` event in "
        "trace order; do not deduplicate repeated calls. Include the `call` "
        f"event that begins invocation {TARGET_INVOCATION} itself. Do not "
        "include calls to untracked functions, builtins, methods on AST node "
        "objects, or any call that happens only before invocation "
        f"{TARGET_INVOCATION} starts or after it returns.\n\n"
        "**File path format**: each `file` value is the repository-relative "
        "path beginning with `src/jinja2/` (for example "
        "`src/jinja2/visitor.py`).\n\n"
        "Return JSON with exactly one top-level key `function_call_order` "
        "whose value is a list of objects, each with keys `file` (string) and "
        "`func` (string), in the chronological order defined above."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    sequence = harvest_function_call_order(args.trace_log, TARGET_INVOCATION)

    oracle_answer = {"function_call_order": sequence}
    template_answer = {"function_call_order": [{"file": "str", "func": "str"}]}

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
