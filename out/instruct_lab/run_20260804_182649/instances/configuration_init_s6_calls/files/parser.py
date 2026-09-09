#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/configuration.py"
TARGET_FUNC = "instructlab.configuration.init"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "instructlab.configuration._expand_paths",
    "instructlab.configuration._expand_value",
    "instructlab.configuration.ensure_storage_directories_exist",
    "instructlab.configuration.finish_additional_train_args",
    "instructlab.configuration.get_default_config",
    "instructlab.configuration.get_dict",
    "instructlab.configuration.read_and_create_system_profiles",
    "instructlab.configuration.recreate_system_profiles",
}
INVOCATION = 13
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

    invocation = 0
    selected_active = False
    selected_finished = False
    target_events = 0
    called_functions = set()
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

        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                invocation += 1
                if invocation == INVOCATION:
                    selected_active = True

        if selected_active and event == "call":
            function_call_order.append({"file": TARGET_FILE, "func": func})
            called_functions.add(func)

        if selected_active and func == TARGET_FUNC and event == "return":
            selected_active = False
            selected_finished = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation < INVOCATION:
        fail(f"trace contains only {invocation} target invocation(s)")
    if not selected_finished:
        fail(f"target invocation {INVOCATION} has no terminating return event")
    if called_functions != TRACKED_FUNCS:
        missing = sorted(TRACKED_FUNCS - called_functions)
        fail(f"selected invocation did not call every tracked function: {missing}")
    if not function_call_order:
        fail(f"target invocation {INVOCATION} contains zero tracked call events")
    return function_call_order


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    function_call_order = parse_trace(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/configuration_init_s6_calls/files/testcase.py::"
        "TestConfigurationRootCalls::test_seeded_root_cli_invocations` against this "
        "repository. During the thirteenth invocation of "
        "`instructlab.configuration.init` in "
        "`src/instructlab/configuration.py`, what is the exact ordered sequence of "
        "runtime calls in the tracked set consisting of exactly "
        "`instructlab.configuration.init`, "
        "`instructlab.configuration.ensure_storage_directories_exist`, "
        "`instructlab.configuration.recreate_system_profiles`, "
        "`instructlab.configuration.read_and_create_system_profiles`, "
        "`instructlab.configuration.get_default_config`, "
        "`instructlab.configuration.get_dict`, "
        "`instructlab.configuration.finish_additional_train_args`, "
        "`instructlab.configuration._expand_paths`, and "
        "`instructlab.configuration._expand_value`? An invocation is one Python "
        "runtime `call` event for exactly `instructlab.configuration.init`, counted "
        "1-based in chronological order from the start of the named test. A function "
        "identity uses fully qualified `module.qualname` form (for example, "
        "`package.module.Class.method`). Include the selected target invocation's own "
        "`call` event, then every `call` event for any function in the exact tracked "
        "set that occurs after it while that selected target invocation remains on "
        "the call stack, ending immediately before the selected target's `return` "
        "event. Include tracked calls reached either directly from the target frame "
        "or transitively through any nested calls. Exclude calls to every function "
        "outside the exact tracked set, including builtins, methods, comprehensions, "
        "and nested helper functions not named above; also exclude all line, return, "
        "and exception events. None of the tracked functions is a generator, so there "
        "are no generator resumptions; if the same tracked function is called more "
        "than once, retain every call as a separate entry. Preserve the single total "
        "chronological event order exactly, with the earlier observed call first; do "
        "not sort or deduplicate, and no tie-breaker is needed because Python call "
        "events are observed sequentially. Return exactly one JSON object with key "
        "`function_call_order`. Its value is a JSON array whose entries have exactly "
        "the keys `file` and `func` in that key order. For every entry, `file` is the "
        "repo-relative POSIX path string of the called function's source file and "
        "`func` is its fully qualified function identity as defined above. Serialize "
        "both values as ordinary JSON strings, not Python `repr`; there are no null, "
        "empty, or omitted values."
    )
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": question,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": function_call_order},
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
