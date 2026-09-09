from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TARGET = "flask.json.tag.TaggedJSONSerializer._untag_scan"
TARGET_FILE = "src/flask/json/tag.py"
TRACKED = {
    TARGET,
    "flask.json.tag.TaggedJSONSerializer.untag",
    "flask.json.tag.TagDict.to_python",
    "flask.json.tag.TagTuple.to_python",
    "flask.json.tag.TagBytes.to_python",
    "flask.json.tag.TagMarkup.to_python",
    "flask.json.tag.TagUUID.to_python",
    "flask.json.tag.TagDateTime.to_python",
}

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/tag_untag_scan_s6_calls/files/testcase.py::"
    "UntagScanCallTest::test_seeded_nested_tagged_values`. "
    "During invocation 1 of exactly "
    "`flask.json.tag.TaggedJSONSerializer._untag_scan`, whose frame is "
    "defined in the repo-relative file `src/flask/json/tag.py`, report the "
    "ordered sequence of qualifying Python runtime call events. An invocation "
    "means one `call` event entering that exact function during the test run, "
    "numbered 1-based in chronological event order; recursive entries are "
    "separate later invocations. The interval for invocation 1 begins with and "
    "includes the call event that enters invocation 1 and ends immediately "
    "before its matching return event, so invocation 1 itself is included. "
    "A call qualifies exactly when its function is one of: "
    "`flask.json.tag.TaggedJSONSerializer._untag_scan`, "
    "`flask.json.tag.TaggedJSONSerializer.untag`, "
    "`flask.json.tag.TagDict.to_python`, "
    "`flask.json.tag.TagTuple.to_python`, "
    "`flask.json.tag.TagBytes.to_python`, "
    "`flask.json.tag.TagMarkup.to_python`, "
    "`flask.json.tag.TagUUID.to_python`, or "
    "`flask.json.tag.TagDateTime.to_python`. Include qualifying calls made at "
    "any nested or transitive depth while invocation 1 remains on the call "
    "stack, not only calls made directly by its frame. Exclude every function "
    "outside that exact set, including built-ins and the implicit "
    "`<dictcomp>` and `<listcomp>` frames. Preserve every repeated qualifying "
    "call. None of the listed functions is a generator; in general, if a "
    "listed function were a generator, each runtime call event on initial "
    "entry or resumption would be a separate sequence element. Order elements "
    "by the runtime's total event-emission order from first to last; do not "
    "sort or deduplicate them, and no tie-breaker is needed because events are "
    "processed sequentially. "
    "Represent function identity as the full dotted runtime module plus "
    "qualified name in `module.Class.method` form (for example, "
    "`sample.worker.Engine.run`). Return exactly one JSON object with the sole "
    "key `function_call_order`. Its value is a JSON array whose objects each "
    "have exactly two keys: `file`, a JSON string containing the repo-relative "
    "path where that called function's frame is defined, and `func`, a JSON "
    "string containing its full dotted function identity. For this qualifying "
    "set the file path is obtained by converting the frame's absolute source "
    "path to the exact repository-relative POSIX path. Emit both fields as "
    "plain strings exactly as defined, without applying `repr()` or `str()`, "
    "and do not emit null or an empty placeholder."
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_events(trace_path: Path) -> list[tuple[str, str, str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match:
            events.append(
                (
                    match.group("path"),
                    match.group("func"),
                    match.group("event"),
                )
            )

    if not any(func == TARGET for _, func, _ in events):
        fail(f"trace contains zero events for target function {TARGET}")
    return events


def compute_order(events: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    active_depth = 0
    started = False
    completed = False
    answer = []

    for path, func, event in events:
        if not started:
            if func != TARGET or event != "call":
                continue
            started = True
            active_depth = 1
        elif func == TARGET:
            if event == "call":
                active_depth += 1
            elif event == "return":
                active_depth -= 1
                if active_depth == 0:
                    completed = True
                    break

        if active_depth > 0 and event == "call" and func in TRACKED:
            normalized = path.replace("\\", "/")
            marker = f"/{TARGET_FILE}"
            if not normalized.endswith(marker):
                fail(f"qualifying call came from unexpected file: {path}")
            answer.append({"file": TARGET_FILE, "func": func})

    if not started:
        fail("target invocation 1 has no call event")
    if not completed:
        fail("target invocation 1 has no matching return event")
    if not answer:
        fail("computed function call order is empty")
    if len({item["func"] for item in answer}) < 2:
        fail("computed function call order contains fewer than two functions")
    return answer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {
            "function_call_order": compute_order(parse_events(args.trace_log))
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
