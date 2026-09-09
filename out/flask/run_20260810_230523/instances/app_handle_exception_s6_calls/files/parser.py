#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/app.py"
TARGET_FUNC = "flask.app.Flask.handle_exception"
INVOCATION = 23
TRACKED_FUNCS = {
    "flask.app.Flask.ensure_sync",
    "flask.app.Flask.finalize_request",
    "flask.app.Flask.handle_exception",
    "flask.app.Flask.log_exception",
    "flask.app.Flask.make_response",
    "flask.app.Flask.process_response",
}

QUESTION = """Run the pytest test `flask_qa/app_handle_exception_s6_calls/files/testcase.py::TestIndirectExceptionCallGraph::test_generated_requests_exercise_error_pipeline`. During that test run, consider the 23rd invocation of `flask.app.Flask.handle_exception` in `src/flask/app.py`. What is the exact ordered sequence of calls to this tracked set of functions: `flask.app.Flask.handle_exception`, `flask.app.Flask.ensure_sync`, `flask.app.Flask.log_exception`, `flask.app.Flask.finalize_request`, `flask.app.Flask.make_response`, and `flask.app.Flask.process_response`?

An invocation is one Python `call` trace event for `flask.app.Flask.handle_exception`, numbered from 1 in chronological event order across the entire test run. For invocation 23, begin with that invocation's own `call` event and continue through its corresponding `return` event. Include a call whenever a Python `call` trace event for one of the six functions listed above occurs while this invocation of the target is on the call stack. Thus the target's own call is included, as are both direct calls from its frame and nested or transitive calls made before it returns. Exclude every function outside the listed set, including builtins, test callbacks, comprehension frames, and other Flask functions. Retain every repeated call without deduplication. If a listed generator function is resumed and Python emits another `call` event for that resumption, count that event as another call.

Return exactly one JSON object with the shape `{"function_call_order": [{"file": "...", "func": "..."}]}`. `function_call_order` is a JSON array in chronological `call`-event order; if events have indistinguishable clock times, their order in the runtime event stream is the tie-breaker. Do not sort or deduplicate the array. Each entry has exactly two JSON-string fields, written with `file` first and `func` second. `file` is the POSIX-style repository-relative path of the called function's source file, and `func` is its full dotted Python identity in `module.Class.method` or `module.function` form (for example, an unrelated call could use `{"file": "src/flask/blueprints.py", "func": "flask.blueprints.Blueprint.register"}`). Use no `repr()` wrapping, shortened class name, or leading repository prefix for either string. The only output keys are `function_call_order`, `file`, and `func`; no line numbers, return events, exception events, or local values are included."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line: str) -> dict[str, object] | None:
    match = re.match(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} "
        r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
        r"event=(?P<event>\w+)\b",
        raw_line,
    )
    if match is None:
        return None

    return {
        "file": match.group("file").replace("\\", "/"),
        "func": match.group("func"),
        "event": match.group("event"),
    }


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    target_events = 0

    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if event is None or not str(event["file"]).endswith(TARGET_FILE):
            continue
        if event["func"] == TARGET_FUNC:
            target_events += 1
        if event["func"] in TRACKED_FUNCS:
            events.append(event)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_count = 0
    collecting = False
    call_order: list[dict[str, str]] = []
    completed = False

    for event in events:
        if event["func"] == TARGET_FUNC and event["event"] == "call":
            invocation_count += 1
            if invocation_count == INVOCATION:
                collecting = True

        if collecting and event["event"] == "call":
            call_order.append(
                {"file": TARGET_FILE, "func": str(event["func"])}
            )

        if (
            collecting
            and event["func"] == TARGET_FUNC
            and event["event"] == "return"
        ):
            completed = True
            break

    if invocation_count < INVOCATION:
        fail(
            f"trace contains only {invocation_count} invocations of "
            f"{TARGET_FUNC}, expected at least {INVOCATION}"
        )
    if not completed:
        fail(f"invocation {INVOCATION} of {TARGET_FUNC} has no return event")
    if len(call_order) < 2:
        fail(f"invocation {INVOCATION} produced an unexpectedly thin call order")

    observed_funcs = {entry["func"] for entry in call_order}
    missing = sorted(TRACKED_FUNCS - observed_funcs)
    if missing:
        fail(f"tracked functions absent from selected invocation: {missing}")

    return {"function_call_order": call_order}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": harvest(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
