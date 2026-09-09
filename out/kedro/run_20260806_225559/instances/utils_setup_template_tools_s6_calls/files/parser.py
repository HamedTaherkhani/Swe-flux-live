import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "kedro/templates/project/hooks/utils.py"
TARGET_FUNC = "kedro.templates.project.hooks.utils.setup_template_tools"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "kedro.templates.project.hooks.utils._remove_dir",
    "kedro.templates.project.hooks.utils._remove_extras_from_kedro_datasets",
    "kedro.templates.project.hooks.utils._remove_file",
    "kedro.templates.project.hooks.utils._remove_from_file",
    "kedro.templates.project.hooks.utils._remove_from_toml",
    "kedro.templates.project.hooks.utils._remove_nested_section",
    "kedro.templates.project.hooks.utils._remove_pyspark_starter_files",
}
EVENT_RE = re.compile(
    r" (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the pytest test "
    "`kedro_qa/utils_setup_template_tools_s6_calls/files/testcase.py::"
    "TestSetupTemplateToolsCalls::test_programmatic_template_cleanup_call_order`. "
    "During that test, consider invocation 1 of "
    "`kedro.templates.project.hooks.utils.setup_template_tools` in "
    "`kedro/templates/project/hooks/utils.py`. An invocation is one Python "
    "`call` event for exactly that function, counted 1-based in chronological "
    "order over the single-threaded test run; calls of nested functions are not "
    "additional target invocations. Report the ordered calls from this exact "
    "tracked set: `kedro.templates.project.hooks.utils.setup_template_tools`, "
    "`kedro.templates.project.hooks.utils._remove_dir`, "
    "`kedro.templates.project.hooks.utils._remove_extras_from_kedro_datasets`, "
    "`kedro.templates.project.hooks.utils._remove_file`, "
    "`kedro.templates.project.hooks.utils._remove_from_file`, "
    "`kedro.templates.project.hooks.utils._remove_from_toml`, "
    "`kedro.templates.project.hooks.utils._remove_nested_section`, and "
    "`kedro.templates.project.hooks.utils._remove_pyspark_starter_files`. "
    "Start with the `call` event that enters target invocation 1, include that "
    "event itself, then include every `call` event for an exact member of the "
    "tracked set that occurs while that target invocation remains on the call "
    "stack, stopping at its matching `return` event. Thus both direct calls "
    "from the target frame and nested/transitive calls are included. Calls to "
    "all other functions (including builtins and comprehension frames) are "
    "excluded. Preserve every repeated event without deduplication; if a "
    "tracked function were a generator, each generator resumption that emits "
    "a Python `call` event would be a separate entry. Order entries by the "
    "interpreter's chronological event order, with no sorting; the test is "
    "single-threaded, so event position is the total-order tie-breaker. "
    "Function identity is the full dotted `module.qualname` recorded above "
    "(for example, `example.module.Widget.run`, not `Widget.run` or `run`). "
    "For each call, `file` is the repository-relative path of the executing "
    "source file, using `/` separators, and `func` is that exact full dotted "
    "function identity; both are JSON strings containing their literal text, "
    "without `repr()` quotes or other normalization. Return exactly one JSON "
    "object with key `function_call_order`, whose value is a JSON array of "
    "objects, each containing exactly `file` then `func` as string-valued keys. "
    "Do not add indices or any other fields."
)


def _read_events(trace_path: Path) -> list[tuple[str, str, str]]:
    if not trace_path.exists():
        raise SystemExit(f"ERROR: trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    events = []
    target_event_count = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        file_name = match.group("file").replace("\\", "/")
        function_name = match.group("func")
        if function_name == TARGET_FUNC:
            target_event_count += 1
        if file_name.endswith(TARGET_FILE):
            events.append((function_name, match.group("event"), TARGET_FILE))

    if target_event_count == 0:
        raise SystemExit(
            f"ERROR: trace contains zero events for target function {TARGET_FUNC}"
        )
    return events


def _first_invocation_call_order(
    events: list[tuple[str, str, str]],
) -> list[dict[str, str]]:
    active = False
    completed = False
    calls = []

    for function_name, event, file_name in events:
        if not active:
            if function_name == TARGET_FUNC and event == "call":
                active = True
                calls.append({"file": file_name, "func": function_name})
            continue

        if function_name == TARGET_FUNC and event == "call":
            raise SystemExit(
                "ERROR: target invocation 1 recursively re-entered before returning"
            )
        if function_name == TARGET_FUNC and event == "return":
            completed = True
            break
        if event == "call" and function_name in TRACKED_FUNCS:
            calls.append({"file": file_name, "func": function_name})

    if not active:
        raise SystemExit("ERROR: target trace has no call event")
    if not completed:
        raise SystemExit("ERROR: target invocation 1 has no matching return event")
    if len(calls) < 2 or len({entry["func"] for entry in calls}) < 2:
        raise SystemExit("ERROR: tracked call order is unexpectedly trivial")
    return calls


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    events = _read_events(Path(args.trace_log))
    call_order = _first_invocation_call_order(events)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
