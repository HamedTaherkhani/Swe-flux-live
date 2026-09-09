#!/usr/bin/env python3
"""Parse trace log into oracle.json for lexer_tokeniter_s1_cfg."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/lexer.py"
TARGET_FUNC = "jinja2.lexer.Lexer.tokeniter"
DEF_LINE = 669
TARGET_INVOCATION = 4

QUESTION = """\
During the pytest run identified by the test id \
`jinja_qa/lexer_tokeniter_s1_cfg/files/testcase.py::TestLexerTokenizeBatch::test_sequential_tokenize`, \
consider every trace event for the function `jinja2.lexer.Lexer.tokeniter` defined in \
`src/jinja2/lexer.py` (the `def tokeniter` line is line 669 in that file).

`Lexer.tokeniter` is a generator. In CPython's `sys.settrace` semantics, a `call` \
event is emitted both when the generator is first entered and on every resume after a \
`yield`. For this question, an **invocation** means a `call` event whose line number \
is exactly 669 (the `def` line). Ignore `call` events at any other line number \
(generator resumptions). Number invocations **1-based** in the chronological order of \
those def-line `call` events across the entire pytest run.

Report the **executed_path** for **invocation 4**: the ordered sequence of `line` \
trace events for `jinja2.lexer.Lexer.tokeniter` that belong to that invocation. \
Collect every `line` event starting immediately after invocation 4's def-line `call` \
event and continuing through all generator resumptions within the same logical run, \
stopping immediately before the next def-line `call` event (invocation 5) if one \
exists, or at end of trace otherwise. Include only events whose `event` type is `line`; \
exclude `call`, `return`, and `exception` events. The `def` line (669) never appears \
because it only produces a `call` event, not a `line` event.

Each executed_path element is an object with three keys:
- `file`: repo-relative path `src/jinja2/lexer.py` (always this exact string).
- `func`: fully qualified name `jinja2.lexer.Lexer.tokeniter` (always this exact string).
- `line`: 1-based line number in `src/jinja2/lexer.py` as it exists in the repository.

Line numbers follow CPython's executed-line reporting: for a multi-line statement, use \
the line where the statement begins (for example, if an `elif` condition spans lines \
10–13 in some function, the first executed line inside that condition might be 11 \
rather than 10). Inside `tokeniter`, several `elif` conditions and `raise` calls \
span multiple physical lines; always report the line number CPython attributes to \
each executed `line` event.

Preserve chronological order exactly as traced. Do not sort, deduplicate, or collapse \
consecutive duplicate line numbers.

Return JSON with top-level key `executed_path` whose value is the list described above.\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _parse_trace_events(trace_log: Path) -> list[tuple[str, str, int, str]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[str, str, int, str]] = []
    for raw_line in text.splitlines():
        if TARGET_FUNC not in raw_line:
            continue
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        rel_file = _repo_relative_path(match.group("file"))
        if rel_file != TARGET_REL_FILE:
            continue
        events.append(
            (
                rel_file,
                match.group("func"),
                int(match.group("line")),
                match.group("event"),
            )
        )

    if not events:
        raise SystemExit(
            f"ERROR: no trace events for {TARGET_FUNC} in {trace_log}"
        )

    return events


def _def_line_call_indices(events: list[tuple[str, str, int, str]]) -> list[int]:
    return [
        index
        for index, (_file, _func, line, event) in enumerate(events)
        if event == "call" and line == DEF_LINE
    ]


def _executed_path_for_invocation(
    events: list[tuple[str, str, int, str]], invocation: int
) -> list[dict[str, object]]:
    def_calls = _def_line_call_indices(events)
    if len(def_calls) < invocation:
        raise SystemExit(
            f"ERROR: expected at least {invocation} def-line call events, "
            f"found {len(def_calls)}"
        )

    start = def_calls[invocation - 1] + 1
    end = def_calls[invocation] if invocation < len(def_calls) else len(events)

    path: list[dict[str, object]] = []
    for file_path, func, line, event in events[start:end]:
        if event != "line":
            continue
        path.append({"file": file_path, "func": func, "line": line})

    if not path:
        raise SystemExit(
            f"ERROR: invocation {invocation} produced an empty executed_path"
        )

    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    executed_path = _executed_path_for_invocation(events, TARGET_INVOCATION)

    oracle_answer = {"executed_path": executed_path}
    template_answer = {
        "executed_path": [{"file": "str", "func": "str", "line": "int"}]
    }

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
