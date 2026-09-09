#!/usr/bin/env python3
"""Parse trace log for S1_IntraProceduralCFG executed_path oracle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/_windows_renderer.py"
TARGET_FUNC = "rich._windows_renderer.legacy_windows_render"
INVOCATION_INDEX = 3

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

QUESTION = (
    "For pytest test "
    "`rich_qa/windows_renderer_legacy_windows_render_s1_cfg/files/testcase.py::"
    "TestLegacyWindowsRenderExecutedPath::test_programmatic_multi_invocation_render`, "
    f"consider `{TARGET_FUNC}` in `{TARGET_FILE}` during that test run.\n\n"
    "Invocation counting: an invocation is one `call` event for this qualname "
    "during the test, numbered chronologically from 1. Report the executed "
    f"path for invocation {INVOCATION_INDEX} only.\n\n"
    "An executed-path element is one `line` trace event whose qualname equals "
    f"`{TARGET_FUNC}` and whose file path ends with `{TARGET_FILE}`. Include "
    "only `line` events (exclude `call`, `return`, and `exception`). Preserve "
    "chronological order; do not deduplicate repeated lines. The `def` line "
    f"(line 7) does not appear because CPython emits `call` on that line, not "
    "`line`. Multi-line statements are not present in this function body; each "
    "executed statement maps to a single source line.\n\n"
    "Each path element is an object with keys `file`, `func`, and `line`. "
    f"`file` is the repo-relative path `{TARGET_FILE}`. `func` is the dotted "
    f"qualname `{TARGET_FUNC}`. `line` is the 1-based source line number in "
    "that file.\n\n"
    "Return JSON with top-level key `executed_path` whose value is the ordered "
    "list of those objects."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.find(TARGET_FILE)
    if idx == -1:
        return normalized
    return normalized[idx:]


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
            }
        )
    return events


def _invocation_slice(events: list[dict], index: int) -> list[dict]:
    call_positions = [i for i, ev in enumerate(events) if ev["event"] == "call"]
    if len(call_positions) < index:
        raise SystemExit(
            f"Expected at least {index} call event(s) for {TARGET_FUNC}, "
            f"found {len(call_positions)}"
        )
    start = call_positions[index - 1]
    end = start
    for i in range(start, len(events)):
        if events[i]["event"] == "return":
            end = i
            break
    return events[start : end + 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    invocation_events = _invocation_slice(events, INVOCATION_INDEX)
    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": ev["lineno"]}
        for ev in invocation_events
        if ev["event"] == "line"
    ]
    if not executed_path:
        raise SystemExit(
            f"No line events for invocation {INVOCATION_INDEX} of {TARGET_FUNC}"
        )

    oracle_answer = {"executed_path": executed_path}
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
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
