#!/usr/bin/env python3
"""Parse trace log into M3_ProgramState oracle for rich.cells.split_graphemes."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "M3_ProgramState"
TARGET_FILE = "rich/cells.py"
TARGET_FUNC = "rich.cells.split_graphemes"
TRACKED_VARIABLE = "total_width"

QUESTION = """\
During pytest run rich_qa/cells_split_graphemes_m3_state/files/testcase.py::SplitGraphemesProgramStateTest, aggregate observations across all twelve test methods in that class (every def test_... method), in pytest collection order.

Consider the function rich.cells.split_graphemes defined in rich/cells.py (the def statement begins on line 161). The test reaches it only indirectly through callers such as chop_cells, set_cell_size, and split_text; your answer must still describe runtime state inside split_graphemes itself.

Track the local variable total_width only. Whenever total_width appears as a key in the locals= mapping attached to any trace event whose func equals rich.cells.split_graphemes (module-qualified dotted name, e.g. rich.cells.split_graphemes), record Python repr(total_width) at that moment. total_width is an int in this function; its repr is the decimal numeral with no surrounding quotes (for example repr(7) is the one-character string whose sole code point is U+0037 DIGIT SEVEN, which JSON-encodes as "7"). Events to scan are call, line, return, and exception events for that frame across every invocation during the test run (one invocation = one call event for split_graphemes, in chronological order). On return events the logged locals dictionary may contain the full final frame locals rather than only changed names—still record total_width when present. Line numbers in trace events are absolute 1-based lines in rich/cells.py; the def line (161), decorators, and docstring are not executed and never produce line events.

Do not invent values from source inspection; only values actually present in logged locals dictionaries count. If the same repr appears on multiple events or invocations, include it once. Sort the final list of distinct repr strings in ascending lexicographic order (Unicode code-point order, the default for Python str.sort()).

Report the answer as JSON with top-level key unique_values whose value is a list of strings, each string being one distinct repr(total_width) observed as defined above.\
"""

TEMPLATE_ANSWER = {"unique_values": ["str"]}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})\s*$"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"could not parse locals dict: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"locals is not a dict: {raw!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _split_trace_line(line: str) -> tuple[str, str, str, dict[str, str]] | None:
    match = TRACE_LINE_RE.match(line.strip())
    if not match:
        return None
    file_path = _normalize_file(match.group("file"))
    if file_path != TARGET_FILE:
        return None
    func = match.group("func")
    if func != TARGET_FUNC:
        return None
    event = match.group("event")
    if event not in {"call", "line", "return", "exception"}:
        return None
    locals_dict = _parse_locals(match.group("locals"))
    return file_path, func, event, locals_dict


def _collect_unique_total_width(trace_path: Path) -> list[str]:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    observed: set[str] = set()
    target_events = 0

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        _file, _func, _event, locals_dict = parsed
        target_events += 1
        if TRACKED_VARIABLE in locals_dict:
            observed.add(locals_dict[TRACKED_VARIABLE])

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not observed:
        raise SystemExit(
            f"no observations of {TRACKED_VARIABLE!r} in trace for {TARGET_FUNC}"
        )

    return sorted(observed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    unique_values = _collect_unique_total_width(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {"unique_values": unique_values},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
