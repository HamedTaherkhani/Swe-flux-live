#!/usr/bin/env python3
"""Parse trace log for S2_Loops oracle (loop iteration count)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/traceback.py"
TARGET_FUNC = "rich.traceback.Traceback._render_stack"
TARGET_FUNC_SUFFIX = "Traceback._render_stack"
LOOP_HEADER_LINE = 792
INVOCATION_INDEX = 1

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

QUESTION = (
    "For pytest test "
    "`rich_qa/traceback_render_stack_s2_loops/files/testcase.py::"
    "TestRenderStackTraceLoop::test_console_print_traceback`, consider "
    f"`{TARGET_FUNC}` in `{TARGET_FILE}` during that test run.\n\n"
    "Invocation counting: an invocation is one logical execution of the "
    "target, numbered chronologically from 1. Because `_render_stack` is a "
    "generator (it is wrapped by `@group()` and uses `yield`), CPython's trace "
    "machinery emits a `return` event at each `yield` and a new `call` event "
    "when the generator resumes; treat the first `call` through the final "
    "`return` for this qualname as a single invocation (invocation 1), "
    "ignoring those internal suspend/resume boundaries.\n\n"
    f"In invocation {INVOCATION_INDEX}, the `for` loop whose header is on "
    f"line {LOOP_HEADER_LINE} of `{TARGET_FILE}` "
    "(`for frame_index, frame in enumerate(stack.frames):`). Iteration "
    "counting is 1-based: iteration N is the Nth time the loop body's first "
    "statement executes. The loop body's first statement is the initial "
    "statement in the `for` loop body block (not the `for` header line); use "
    "the line number of that statement as it appears in the repository file.\n\n"
    "Count only `line` events at that body-first line while inside invocation "
    "1 (from its opening `call` through its closing `return`, including across "
    "generator resumes). Report the total number of iterations as integer "
    "`loop_iteration_count`."
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


def _logical_invocation_events(events: list[dict], index: int) -> list[dict]:
    call_idxs = [i for i, ev in enumerate(events) if ev["event"] == "call"]
    if len(call_idxs) < index:
        raise SystemExit(
            f"Expected at least {index} call event(s) for {TARGET_FUNC}, "
            f"found {len(call_idxs)}"
        )
    start = call_idxs[index - 1]
    end = start
    for i in range(start, len(events)):
        if events[i]["event"] == "return":
            end = i
    return events[start : end + 1]


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

    inv_events = _logical_invocation_events(events, INVOCATION_INDEX)
    count = sum(
        1 for ev in inv_events if ev["event"] == "line" and ev["lineno"] == body_line
    )
    if count == 0:
        raise SystemExit(
            f"Zero iterations at loop body line {body_line} for invocation "
            f"{INVOCATION_INDEX}"
        )

    oracle_answer = {"loop_iteration_count": count}
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
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
