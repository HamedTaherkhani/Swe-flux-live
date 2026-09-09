#!/usr/bin/env python3
"""Parse trace logs for utils_urlize_s1_cfg (S1_IntraProceduralCFG executed_path)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/utils.py"
TARGET_FUNC = "jinja2.utils.urlize"
TARGET_INVOCATION = 5

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
)


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_trace_line(raw_line: str) -> dict[str, str | int] | None:
    if raw_line.startswith("[TRACE]"):
        return None
    match = TRACE_LINE_RE.match(raw_line.strip())
    if not match:
        return None
    return {
        "file": _normalize_file(match.group("file")),
        "lineno": int(match.group("lineno")),
        "func": match.group("func"),
        "event": match.group("event"),
    }


def _load_target_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["file"] == TARGET_FILE and parsed["func"] == TARGET_FUNC:
            events.append(parsed)

    if not events:
        _fail(
            f"no trace events for {TARGET_FUNC} in {TARGET_FILE}; "
            f"check TRACE_FILE/TRACE_FUNC configuration"
        )
    return events


def _extract_executed_path(events: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    invocation = 0
    in_target = False
    executed_path: list[dict[str, str | int]] = []

    for event in events:
        kind = str(event["event"])
        lineno = int(event["lineno"])

        if kind == "call":
            invocation += 1
            in_target = invocation == TARGET_INVOCATION
            continue

        if not in_target:
            continue

        if kind in {"return", "exception"}:
            break

        if kind == "line":
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": lineno,
                }
            )

    if invocation < TARGET_INVOCATION:
        _fail(
            f"trace contains only {invocation} invocation(s) of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if not executed_path:
        _fail(
            f"no line events for invocation {TARGET_INVOCATION} of {TARGET_FUNC}"
        )

    return executed_path


def _build_question() -> str:
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/utils_urlize_s1_cfg/files/testcase.py::UrlizeS1CfgTest::"
        "test_urlize_middle_invocation_line_path` (test class `UrlizeS1CfgTest`, "
        "test method `test_urlize_middle_invocation_line_path`). "
        "During that single test run, the function `jinja2.utils.urlize` in "
        "`src/jinja2/utils.py` is invoked multiple times via direct calls. "
        "An invocation is one `call` event for `jinja2.utils.urlize` during "
        "the test run, counted in chronological order starting at 1. "
        f"For invocation {TARGET_INVOCATION} only, report the exact ordered "
        "sequence of `line` trace events recorded while that invocation's "
        "frame is active (from immediately after its `call` event until its "
        "`return` or `exception` event, whichever comes first). Include only "
        "`line` events whose function is exactly `jinja2.utils.urlize`; "
        "exclude `call`, `return`, and `exception` events, and exclude line "
        "events from nested or helper frames such as "
        "`jinja2.utils.urlize.<locals>.trim_url`. "
        "The `def` line of `urlize` does not appear in this sequence because "
        "it is not a `line` event. Decorator lines and docstring lines are "
        "likewise excluded. Line numbers are absolute, 1-based, and refer "
        "to `src/jinja2/utils.py` as it exists in the repository. For "
        "multi-line statements (for example the nested `trim_url` definition "
        "around lines 270-274, the `middle = (` assignment that can begin at "
        "line 323, or the `elif (` email guard that begins at line 333), "
        "attribute each executed-line event to the line where that statement "
        "or compound condition begins. "
        "Each sequence element is a JSON object with exactly three keys: "
        "`file` (repo-relative path string, always `src/jinja2/utils.py`), "
        "`func` (dotted module qualname string, always `jinja2.utils.urlize`), "
        "and `line` (JSON integer line number). Preserve chronological order; "
        "do not sort, deduplicate, or collapse consecutive duplicates. "
        "Report the answer as a JSON object with exactly one key, "
        "`executed_path`, whose value is that ordered list."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _load_target_events(args.trace_log)
    executed_path = _extract_executed_path(events)

    oracle_answer = {"executed_path": executed_path}
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": _build_question(),
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
