#!/usr/bin/env python3
"""Parse trace log into S3_ProgramState oracle for rich.box.Box.get_row."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "S3_ProgramState"
TARGET_FILE = "rich/box.py"
TARGET_FUNC = "rich.box.Box.get_row"
DEF_LINE = 115
TEST_ID = (
    "rich_qa/box_get_row_s3_state/files/testcase.py::"
    "BoxGetRowProgramStateTest::test_seeded_get_row_foot_level"
)
TRACKED_VARIABLE = "parts"
OBSERVATION_LINE = 158
BODY_LINE = 157
TARGET_INVOCATION = 1

QUESTION = f"""\
During pytest run {TEST_ID}, consider the function {TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line {DEF_LINE}).

Track the local variable {TRACKED_VARIABLE} only, during invocation {TARGET_INVOCATION} of {TARGET_FUNC}. An invocation is one call event for {TARGET_FUNC} during the test run; invocations are numbered chronologically starting at 1 (the first call event is invocation 1). Only that invocation contributes to the answer.

Python's sys.settrace hook reports event=line immediately before the named physical line executes (not after). Therefore, the k-th completion of line {BODY_LINE} (`append(horizontal * width)`) within invocation {TARGET_INVOCATION} is identified by the k-th event=line record whose func equals {TARGET_FUNC} exactly (module-qualified dotted name, e.g. rich.box.Box.get_row) and whose absolute 1-based line number in {TARGET_FILE} is {OBSERVATION_LINE} (the physical line immediately following line {BODY_LINE}, which is `if not last:`). The def line ({DEF_LINE}), decorator lines, and docstring lines are not executable and never produce line events. For multi-line statements, the reported line is where the statement begins.

Build the evaluation environment for that invocation by merging locals across frame events until the matching return event: start from the locals= mapping on the call event; for each subsequent event in the same frame before return, for every name that appears in that event's locals= mapping, replace the stored value with the new logged value (names not listed keep their previous value). On return events the logged locals dictionary may contain the full final frame locals rather than only changed names—still apply the same merge rule before the frame ends.

At each completion of line {BODY_LINE} defined above, append one entry to the history in chronological order (first completion first). The recorded value is Python repr({TRACKED_VARIABLE}) taken from the merged environment immediately after applying that observation line's locals= overrides (i.e., the state visible just before line {OBSERVATION_LINE} executes, which is immediately after line {BODY_LINE} has finished for that completion). All values are Python repr strings: lists use square brackets with repr of each element separated by comma-space (for example repr of a two-string list might appear as "['a', 'bb']" in JSON); strings inside the repr use single quotes; ints use decimal numerals without quotes; True and False use Python spellings.

Do not deduplicate: if the same repr appears at multiple completions, include each occurrence in order.

Report JSON with top-level key temporal_value_history whose value is a list of strings, each string being one repr({TRACKED_VARIABLE}) observation in chronological order as defined above.\
"""

TEMPLATE_ANSWER = {"temporal_value_history": ["str"]}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})\s*$"
)


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


def _split_trace_line(line: str) -> tuple[int, str, dict[str, str]] | None:
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
    lineno = int(match.group("line"))
    locals_dict = _parse_locals(match.group("locals"))
    return lineno, event, locals_dict


def _collect_parts_history(trace_path: Path) -> list[str]:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    active_state: dict[str, str] | None = None
    history: list[str] = []

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        lineno, event, changed = parsed
        target_events += 1

        if event == "call" and lineno == DEF_LINE:
            invocation += 1
            active_state = dict(changed)
            continue

        if active_state is None:
            continue

        if event == "return":
            active_state = None
            continue

        active_state.update(changed)

        if (
            event == "line"
            and invocation == TARGET_INVOCATION
            and lineno == OBSERVATION_LINE
        ):
            if TRACKED_VARIABLE not in active_state:
                raise SystemExit(
                    f"{TRACKED_VARIABLE!r} missing from merged locals at "
                    f"line {OBSERVATION_LINE} step {len(history) + 1}"
                )
            history.append(active_state[TRACKED_VARIABLE])

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not history:
        raise SystemExit(
            f"no observations of {TRACKED_VARIABLE!r} at line {OBSERVATION_LINE} "
            f"for invocation {TARGET_INVOCATION}"
        )

    return history


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    temporal_value_history = _collect_parts_history(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {"temporal_value_history": temporal_value_history},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
