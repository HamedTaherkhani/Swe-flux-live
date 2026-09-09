#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/evaluate.py"
TARGET_FUNC = "instructlab.model.evaluate.validate_options"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "instructlab.model.evaluate.validate_model",
}
INVOCATION = 10
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> list[dict]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    invocation = 0
    selected_active = False
    selected_finished = False
    target_events = 0
    tracked_calls = set()
    executed_path = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if not file_name.endswith("/" + TARGET_FILE) or func not in TRACKED_FUNCS:
            continue

        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                invocation += 1
                selected_active = invocation == INVOCATION

        if selected_active and event == "call":
            tracked_calls.add(func)

        if selected_active and event == "line":
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": func,
                    "line": int(match.group("line")),
                }
            )

        if selected_active and func == TARGET_FUNC and event == "return":
            selected_active = False
            selected_finished = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation < INVOCATION:
        fail(f"trace contains only {invocation} target invocation(s)")
    if not selected_finished:
        fail(f"target invocation {INVOCATION} has no terminating return event")
    if tracked_calls != TRACKED_FUNCS:
        missing = sorted(TRACKED_FUNCS - tracked_calls)
        fail(f"selected invocation did not call every tracked function: {missing}")
    if not executed_path:
        fail(f"target invocation {INVOCATION} contains zero tracked line events")
    return executed_path


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    executed_path = parse_trace(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/evaluate_validate_options_s6_calls/files/testcase.py::"
        "TestEvaluateValidationCalls::test_generated_mt_validation_plan` against this "
        "repository. During the tenth invocation of "
        "`instructlab.model.evaluate.validate_options` in "
        "`src/instructlab/model/evaluate.py`, what is the exact chronological "
        "cross-function executed-line path for the tracked function set consisting "
        "of exactly `instructlab.model.evaluate.validate_options` and "
        "`instructlab.model.evaluate.validate_model`? An invocation is one runtime "
        "`call` event for exactly `instructlab.model.evaluate.validate_options`, "
        "counted 1-based in chronological order from the start of the named test. "
        "A function identity uses fully qualified `module.qualname` form (for example, "
        "`package.module.Class.method`). Starting immediately after that invocation's "
        "call event and ending immediately before its return event, include every "
        "runtime `line` event whose active frame is one of the two exact tracked "
        "functions. This includes events in the target frame and in any invocation of "
        "the tracked callee while the selected target invocation remains on the call "
        "stack, whether reached directly or transitively. Exclude all call, return, "
        "and exception events, all functions outside the exact tracked set (including "
        "builtins and comprehension frames), and all events before or after the "
        "selected target frame's lifetime. Neither tracked function is a generator; "
        "therefore generator resumptions add no events or invocations under this rule. "
        "Preserve chronological event order exactly and retain every repeated event; "
        "do not sort or deduplicate. Each line is the absolute 1-based physical line "
        "number reported for that event in the named repository file as it exists "
        "during the test. Do not normalize multi-line statements: if execution reports "
        "an event on a continuation line, use that continuation line's own physical "
        "number. The `def` lines, decorator lines, and docstring-only lines are not "
        "included unless Python emits a runtime line event for them. Return exactly "
        "one JSON object with key `executed_path`. Its value is a JSON array whose "
        "entries have exactly the keys `file`, `func`, and `line` in that key order. "
        "For every entry, `file` is the repo-relative POSIX path string, `func` is the "
        "fully qualified function identity defined above, and `line` is a JSON integer. "
        "Serialize strings as JSON strings and line numbers as JSON numbers; no value "
        "uses Python `repr`, and there are no null, empty, or omitted values."
    )
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": question,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
