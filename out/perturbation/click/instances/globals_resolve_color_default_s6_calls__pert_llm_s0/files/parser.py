from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/globals.py"
REPO_FILE = "src/click/globals.py"
TARGET_FUNC = "click.globals.resolve_color_default"
HELPER_FUNC = "click.globals.get_current_context"
TRACKED_FUNCS = {TARGET_FUNC, HELPER_FUNC}

QUESTION = """Run the single pytest test `click_qa/globals_resolve_color_default_s6_calls/files/testcase.py::TestGeneratedColorResolution::test_programmatic_context_schedule`. During that test method, consider every invocation of the target function `click.globals.resolve_color_default` in `src/click/globals.py`, together with calls to `click.globals.get_current_context`.

What is the exact ordered sequence of qualifying Python `call` events? A qualifying event is (1) every `call` event that begins an invocation of `click.globals.resolve_color_default`, and (2) every `call` event for `click.globals.get_current_context` that occurs while at least one target invocation is active on the Python call stack. Thus target calls are included, and helper calls are included whether made directly by the target frame or transitively beneath it. Calls to builtins, comprehension frames, functions outside this exact two-function set, and helper calls made while no target invocation is active are excluded. Include every repeated qualifying event without sorting or deduplication. If a listed function were a generator, each resumption that produces a Python `call` event would count as a separate event; neither listed function is a generator.

An invocation means one Python `call` event for that function during this test method. Invocations are numbered from 1 in chronological event order, and the requested sequence covers all target invocations from the first through the last. Order the objects by the interpreter's chronological emission order of qualifying events. This event stream is already totally ordered, so use no timestamp or additional tie-breaker.

Return exactly `{"function_call_order": [{"file": "str", "func": "str"}]}`. The `function_call_order` value is a JSON array with one object per qualifying event. In each object, `file` is the repository-relative POSIX path `src/click/globals.py`, and `func` is the full dotted Python identity in `module.Class.method` or `module.function` form; for example, `click.globals.pop_context` illustrates the function format. Emit both as direct JSON strings, not Python `repr()` strings, and do not add invocation numbers or line numbers. The array is non-empty; an empty string, JSON null, or omitted field never represents a call."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    target_events = 0
    target_depth = 0
    observed_functions: set[str] = set()
    call_order: list[dict[str, str]] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue

        filename = match.group("file").replace("\\", "/")
        function = match.group("func")
        event = match.group("event")
        if not filename.endswith(TARGET_FILE_SUFFIX) or function not in TRACKED_FUNCS:
            continue

        if function == TARGET_FUNC:
            target_events += 1

        if event == "call":
            if function == TARGET_FUNC:
                call_order.append({"file": REPO_FILE, "func": function})
                observed_functions.add(function)
                target_depth += 1
            elif target_depth > 0:
                call_order.append({"file": REPO_FILE, "func": function})
                observed_functions.add(function)
        elif event == "return" and function == TARGET_FUNC:
            if target_depth <= 0:
                fail("target return event occurred without an active target invocation")
            target_depth -= 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not call_order:
        fail("trace contains no qualifying call events")
    if target_depth != 0:
        fail(f"trace ended with {target_depth} active target invocation(s)")
    missing = sorted(TRACKED_FUNCS - observed_functions)
    if missing:
        fail(f"trace did not capture all tracked functions: {', '.join(missing)}")

    return {"function_call_order": call_order}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": parse_trace(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
