#!/usr/bin/env python3
"""Parse trace logs for distinct source values at line 130 in BaseLoader.load."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/loaders.py"
TARGET_FUNC = "jinja2.loaders.BaseLoader.load"
CALL_LINE = 107
RETURN_LINE = 149
OBSERVATION_LINE = 130
TRACKED_VARIABLE = "source"

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?(?:\s+exc=(?P<exc>.*?))?\s+locals=(?P<locals>\{.*\})$"
)


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Could not parse locals dict: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected locals dict, got {type(parsed)!r}")
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    groups = match.groupdict()
    return {
        "path": groups["path"].replace("\\", "/"),
        "lineno": groups["lineno"],
        "func": groups["func"],
        "event": groups["event"],
        "locals": groups["locals"] or "{}",
    }


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def harvest_unique_source_values(trace_log: Path) -> list[str]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    in_invocation = False
    merged: dict[str, str] = {}
    target_events = 0
    observed_values: set[str] = set()

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]
        lineno = int(parsed["lineno"])

        if event == "call" and lineno == CALL_LINE:
            in_invocation = True
            merged = {}
            continue

        if not in_invocation:
            continue

        if event == "return" and lineno == RETURN_LINE:
            in_invocation = False
            continue

        if event != "line":
            continue

        merged.update(_parse_locals(parsed["locals"]))

        if lineno == OBSERVATION_LINE and TRACKED_VARIABLE in merged:
            observed_values.add(merged[TRACKED_VARIABLE])

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if not observed_values:
        raise SystemExit(
            f"No observations of {TRACKED_VARIABLE} at line {OBSERVATION_LINE}"
        )

    return sorted(observed_values)


def build_question() -> str:
    return (
        "Consider every test method in "
        "`jinja_qa/loaders_load_m3_state/files/testcase.py::"
        "TestBaseLoaderLoadProgramState`. The answer aggregates behavior across "
        "**all** `test_*` methods in that class, in the chronological order "
        "pytest collects and runs them (definition order in the file).\n\n"
        "Those tests reach `jinja2.loaders.BaseLoader.load` in "
        f"`{TARGET_FILE}` only **indirectly**: each test builds a "
        "`ChoiceLoader` or `PrefixLoader` and calls that composite loader's "
        "`load` method, which delegates to nested `DictLoader` instances whose "
        "`load` implementation is inherited from `BaseLoader`. The tests never "
        "import or call `BaseLoader.load` directly.\n\n"
        "Target function: `jinja2.loaders.BaseLoader.load` (the method "
        f"beginning at line 108 of `{TARGET_FILE}`).\n\n"
        "An **invocation** means one `call` trace event for "
        f"`{TARGET_FUNC}` recorded at absolute line {CALL_LINE} during the "
        "test run. Count invocations in chronological order starting at 1. "
        "Only events whose qualified name is exactly "
        f"`{TARGET_FUNC}` count (not `ChoiceLoader.load` or "
        "`PrefixLoader.load`).\n\n"
        "Within one invocation, maintain a map of local variable bindings by "
        f"scanning every `line` event for `{TARGET_FUNC}` from that invocation's "
        f"`call` at line {CALL_LINE} through the first `line` event at absolute "
        f"line {OBSERVATION_LINE}. Each event's `locals={{...}}` dictionary "
        "supplies bindings that overwrite earlier bindings for the same name; "
        "only keys present in those per-event dictionaries participate.\n\n"
        f"Immediately after line {OBSERVATION_LINE} executes for the first time "
        f"during an invocation, read the binding for `{TRACKED_VARIABLE}` from "
        "the merged map. Collect the binding string from every invocation "
        "across the full test run.\n\n"
        "Each binding string is already Python `repr()` output as it would "
        "appear for that local (strings include their surrounding quote "
        "characters, `None` appears as `None`, booleans as `True`/`False`). "
        "Python chooses single- or double-quote delimiters per its `repr` "
        "rules; for example, a string local holding `hello` is reported as "
        "`'hello'`, while a string whose content includes single-quote "
        "characters is reported with double-quote delimiters such as "
        "`\"say 'hi'\"`.\n\n"
        "Return JSON with top-level key `unique_values`: the sorted list of "
        f"**distinct** binding strings for `{TRACKED_VARIABLE}` observed across "
        "all invocations. Sort ascending by Unicode code-point order on the "
        "binding strings themselves. Remove duplicates; each distinct repr "
        "appears once."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    unique_values = harvest_unique_source_values(args.trace_log)
    oracle_answer = {"unique_values": unique_values}
    template_answer = {"unique_values": ["str"]}

    payload = {
        "question_kind": "M3_ProgramState",
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
