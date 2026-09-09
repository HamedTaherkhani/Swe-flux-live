#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scripts/phased_training_resume.py"
TARGET_FUNC = "scripts.phased_training_resume.run_training_phase"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "scripts.phased_training_resume.assert_phase1_started",
    "scripts.phased_training_resume.assert_phase2_started",
    "scripts.phased_training_resume.assert_phase2_eval_started",
    "scripts.phased_training_resume.assert_phase1_in_journal",
    "scripts.phased_training_resume.assert_phase1_and_phase2_started",
    "scripts.phased_training_resume.assert_phase2_resumed_and_eval_started",
    "scripts.phased_training_resume.assert_completion_resumed",
}
INVOCATION = 3
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_invocations = 0
    selected_active = False
    selected_finished = False
    all_called_functions = set()
    function_call_order = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if not file_name.endswith("/" + TARGET_FILE) or func not in TRACKED_FUNCS:
            continue

        if event == "call":
            all_called_functions.add(func)

        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_invocations += 1
                if target_invocations == INVOCATION:
                    selected_active = True

        if selected_active and event == "call":
            function_call_order.append({"file": TARGET_FILE, "func": func})

        if selected_active and func == TARGET_FUNC and event == "return":
            selected_active = False
            selected_finished = True

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_invocations < INVOCATION:
        fail(
            f"trace contains only {target_invocations} target invocation(s), "
            f"but invocation {INVOCATION} is required"
        )
    if not selected_finished:
        fail(f"target invocation {INVOCATION} has no terminating return event")
    if all_called_functions != TRACKED_FUNCS:
        missing = sorted(TRACKED_FUNCS - all_called_functions)
        unexpected = sorted(all_called_functions - TRACKED_FUNCS)
        fail(
            "the complete test run did not capture the exact tracked function set; "
            f"missing={missing}, unexpected={unexpected}"
        )
    if len(function_call_order) < 2:
        fail(
            f"target invocation {INVOCATION} contains fewer than two tracked call events"
        )
    return function_call_order


def build_question() -> str:
    return (
        "Run the pytest test "
        "`instruct_lab_qa/phased_training_resume_run_training_phase_s6_calls/"
        "files/testcase.py::TestPhasedTrainingResumeCalls::"
        "test_resume_sequence_with_generated_paths` against this repository. During "
        "the third invocation of `scripts.phased_training_resume.run_training_phase` "
        "in `scripts/phased_training_resume.py`, what is the exact ordered sequence "
        "of runtime calls in the tracked set consisting of exactly "
        "`scripts.phased_training_resume.run_training_phase`, "
        "`scripts.phased_training_resume.assert_phase1_started`, "
        "`scripts.phased_training_resume.assert_phase2_started`, "
        "`scripts.phased_training_resume.assert_phase2_eval_started`, "
        "`scripts.phased_training_resume.assert_phase1_in_journal`, "
        "`scripts.phased_training_resume.assert_phase1_and_phase2_started`, "
        "`scripts.phased_training_resume.assert_phase2_resumed_and_eval_started`, and "
        "`scripts.phased_training_resume.assert_completion_resumed`? An invocation "
        "is one Python runtime `call` event for exactly "
        "`scripts.phased_training_resume.run_training_phase`, counted 1-based in "
        "chronological order from the start of the named test. A function identity "
        "uses the executing frame's dotted `module.qualname` form (for example, "
        "`package.module.Class.method`). Include the selected target invocation's own "
        "`call` event, then every `call` event for any function in the exact tracked "
        "set that occurs after it while that selected target invocation remains on "
        "the call stack, ending immediately before the selected target's `return` "
        "event. Include tracked calls reached directly from the target frame and "
        "tracked calls reached transitively through nested calls. Exclude calls to "
        "every function outside the exact tracked set, including builtins, callable "
        "mock objects, context-manager methods, comprehension frames, and nested "
        "functions not named above; also exclude all line, return, and exception "
        "events. None of the tracked functions is a generator, so generator "
        "resumptions contribute no events under this rule. Retain each repeated or "
        "recursive qualifying call as a separate entry. Preserve the single total "
        "chronological event order exactly, with the earlier observed call first; do "
        "not sort or deduplicate, and no tie-breaker is needed because Python call "
        "events are observed sequentially. Return exactly one JSON object with the "
        "sole key `function_call_order`. Its value is a JSON array whose entries have "
        "exactly the keys `file` and `func` in that key order. For every entry, `file` "
        "is the called function's repo-relative POSIX source path and `func` is its "
        "fully qualified function identity defined above. Serialize both as ordinary "
        "JSON strings using JSON escaping, not Python `repr`; there are no null, "
        "empty, or omitted values."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {
            "function_call_order": parse_trace(Path(args.trace_log))
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
