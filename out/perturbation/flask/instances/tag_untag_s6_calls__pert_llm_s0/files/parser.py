#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/json/tag.py"
TARGET_FUNC = "flask.json.tag.TaggedJSONSerializer.untag"
INVOCATION = 1
TRACKED_FUNCS = {
    "flask.json.tag.TagBytes.to_python",
    "flask.json.tag.TagDateTime.to_python",
    "flask.json.tag.TagDict.to_python",
    "flask.json.tag.TagMarkup.to_python",
    "flask.json.tag.TagTuple.to_python",
    "flask.json.tag.TagUUID.to_python",
    "flask.json.tag.TaggedJSONSerializer._untag_scan",
    "flask.json.tag.TaggedJSONSerializer.untag",
}

QUESTION = """Run the pytest test `flask_qa/tag_untag_s6_calls/files/testcase.py::TestTaggedJSONIndirectCalls::test_nested_generated_document_round_trip`. During that test run, consider the 1st invocation of `flask.json.tag.TaggedJSONSerializer.untag` in `src/flask/json/tag.py`. What is the exact ordered sequence of calls to this tracked set of functions: `flask.json.tag.TaggedJSONSerializer.untag`, `flask.json.tag.TaggedJSONSerializer._untag_scan`, `flask.json.tag.TagDict.to_python`, `flask.json.tag.TagTuple.to_python`, `flask.json.tag.TagBytes.to_python`, `flask.json.tag.TagMarkup.to_python`, `flask.json.tag.TagUUID.to_python`, and `flask.json.tag.TagDateTime.to_python`?

An invocation is one Python `call` trace event for `flask.json.tag.TaggedJSONSerializer.untag`, numbered from 1 in chronological event-stream order across the entire test run. Begin with the 1st invocation's own `call` event and end with its corresponding `return` event. Include a call whenever a Python `call` trace event for one of the eight listed functions occurs while that 1st target invocation is on the Python call stack. Thus include the target's own call plus both direct and nested or transitive calls made before it returns. Exclude every function outside the listed set, including builtins, test-defined tag methods, comprehension frames, imported JSON helpers, and all other Flask functions, even when such a function executes while the target is on the stack. Retain every repeated call without deduplication. None of the listed functions is a generator; as a general rule, if a listed generator were resumed and Python emitted another `call` event, that event would be retained as another call.

Return exactly one JSON object with the shape `{"function_call_order": [{"file": "...", "func": "..."}]}`. `function_call_order` is a JSON array in chronological runtime `call`-event order; do not sort or deduplicate it. Event-stream position is the total-order tie-breaker if clock timestamps are equal. Each entry contains exactly two JSON-string fields, serialized with `file` first and `func` second. `file` is the called function's POSIX-style path relative to the repository root, with no leading `./` or absolute prefix. `func` is the full dotted Python identity in `module.Class.method` or `module.function` form; for example, an unrelated function could be represented as `{"file": "src/flask/config.py", "func": "flask.config.Config.from_file"}`. Emit both strings as their plain JSON string values, without `repr()` wrapping or shortened names. The only output keys are `function_call_order`, `file`, and `func`; line numbers, non-call events, return values, and local values are not included."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line: str) -> dict[str, str] | None:
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

    events: list[dict[str, str]] = []
    target_events = 0

    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if event is None or not event["file"].endswith(TARGET_FILE):
            continue
        if event["func"] == TARGET_FUNC:
            target_events += 1
        if event["func"] in TRACKED_FUNCS:
            events.append(event)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_count = 0
    target_depth = 0
    collecting = False
    completed = False
    call_order: list[dict[str, str]] = []

    for event in events:
        is_target_call = (
            event["func"] == TARGET_FUNC and event["event"] == "call"
        )
        if is_target_call:
            invocation_count += 1
            if invocation_count == INVOCATION:
                collecting = True
                target_depth = 1
            elif collecting:
                target_depth += 1

        if collecting and event["event"] == "call":
            call_order.append(
                {"file": TARGET_FILE, "func": event["func"]}
            )

        if (
            collecting
            and event["func"] == TARGET_FUNC
            and event["event"] == "return"
        ):
            target_depth -= 1
            if target_depth == 0:
                completed = True
                break

    if invocation_count < INVOCATION:
        fail(
            f"trace contains only {invocation_count} invocations of "
            f"{TARGET_FUNC}, expected at least {INVOCATION}"
        )
    if not completed:
        fail(f"invocation {INVOCATION} of {TARGET_FUNC} has no return event")
    if len(call_order) < 10:
        fail(
            f"invocation {INVOCATION} produced only {len(call_order)} tracked calls"
        )

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
