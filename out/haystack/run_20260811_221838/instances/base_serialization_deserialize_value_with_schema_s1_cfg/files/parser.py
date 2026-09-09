#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/utils/base_serialization.py"
TARGET_QUALNAME = "haystack.utils.base_serialization._deserialize_value_with_schema"
SELECTED_INVOCATION = 9

QUESTION = """Run the single pytest item `haystack_qa/base_serialization_deserialize_value_with_schema_s1_cfg/files/testcase.py::TestDeserializeValueWithSchemaCFG::test_programmatic_nested_object_path`, defined by class `TestDeserializeValueWithSchemaCFG` and method `test_programmatic_nested_object_path`.

For the ninth invocation of `haystack.utils.base_serialization._deserialize_value_with_schema`, defined in `haystack/utils/base_serialization.py` beginning at line 186, report the exact ordered sequence of executed line events inside that invocation's own frame. Invocation counting is 1-based in chronological order of `call` events for this exact function during the test item: the first such `call` is invocation 1, recursive calls count as additional invocations when their own `call` events occur, and calls of every other function are excluded.

An executed line is one CPython `sys.settrace` `line` event whose code file is exactly the named repository file, whose function name is exactly `haystack.utils.base_serialization._deserialize_value_with_schema`, and whose frame is the selected invocation. Exclude `call`, `return`, and `exception` events. Also exclude line events from recursive child invocations and from nested comprehension or helper-function frames, even when their qualified names begin with the target's name. Preserve chronological event order and preserve every duplicate; do not sort or deduplicate. Line numbers are absolute 1-based physical line numbers in the named file as it exists in the repository. The `def` line, decorator lines, and docstring lines do not appear unless CPython emits a `line` event for them; in this function the `def` line does not appear. For a multi-line statement, call, or condition, report the line event at the physical line where that statement or expression begins, as supplied by the event frame's `f_lineno`; do not independently add its continuation lines.

Return exactly one JSON object with key `executed_path`. Its value is a list in the preserved event order. Every element has exactly the shape `{"file": <str>, "func": <str>, "line": <int>}`: `file` is always the repo-relative string `haystack/utils/base_serialization.py`, `func` is always the fully dotted string `haystack.utils.base_serialization._deserialize_value_with_schema`, and `line` is a decimal JSON integer (never a string or null)."""


def _read_selected_path(trace_path: Path) -> list[int]:
    try:
        text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read trace log {trace_path}: {exc}") from exc
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        rf"\s(?P<file>\S*{re.escape(TARGET_FILE)}):(?P<line>\d+)\s+"
        rf"{re.escape(TARGET_QUALNAME)}\s+event=(?P<event>call|line|return|exception)\b"
    )
    invocations: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    target_event_count = 0

    for raw_line in text.splitlines():
        match = event_pattern.search(raw_line)
        if match is None:
            continue
        target_event_count += 1
        event = match.group("event")
        if event == "call":
            invocation: dict[str, object] = {"lines": [], "completed": False}
            invocations.append(invocation)
            active.append(invocation)
        elif event == "line":
            if not active:
                raise RuntimeError("line event encountered without an active target invocation")
            lines = active[-1]["lines"]
            if not isinstance(lines, list):
                raise RuntimeError("internal invocation state is invalid")
            lines.append(int(match.group("line")))
        elif event == "return":
            if not active:
                raise RuntimeError("return event encountered without an active target invocation")
            active[-1]["completed"] = True
            active.pop()

    if target_event_count == 0:
        raise RuntimeError(f"trace log contains zero events for {TARGET_QUALNAME}")
    if len(invocations) < SELECTED_INVOCATION:
        raise RuntimeError(
            f"expected at least {SELECTED_INVOCATION} invocations of {TARGET_QUALNAME}, found {len(invocations)}"
        )
    if active:
        raise RuntimeError(f"trace ended with {len(active)} incomplete target invocation(s)")

    selected = invocations[SELECTED_INVOCATION - 1]
    if not selected["completed"]:
        raise RuntimeError(f"selected invocation {SELECTED_INVOCATION} did not complete")
    selected_lines = selected["lines"]
    if not isinstance(selected_lines, list) or not selected_lines:
        raise RuntimeError(f"selected invocation {SELECTED_INVOCATION} contains zero line events")
    return selected_lines


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    lines = _read_selected_path(args.trace_log)
    answer = {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_QUALNAME, "line": line}
            for line in lines
        ]
    }
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
