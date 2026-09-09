#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/data/loader.py"
TARGET_FUNC = "llamafactory.data.loader.get_dataset"
SELECTED_INVOCATION = 4
TRACKED_FUNCS = {
    TARGET_FUNC,
    "llamafactory.data.loader._get_merged_dataset",
    "llamafactory.data.loader._get_preprocessed_dataset",
    "llamafactory.data.loader._get_dataset_processor",
}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/loader_get_dataset_s6_calls/files/testcase.py::"
    "TestIndirectDatasetModuleCallGraph::test_seeded_multi_stage_dataset_modules`. During that complete "
    "test run, consider the 4th invocation of `llamafactory.data.loader.get_dataset` in "
    "`src/llamafactory/data/loader.py`. An invocation is one Python `call` event for that exact "
    "function, and invocations are numbered 1-based in chronological runtime event order. Report "
    "`function_call_order`: the chronological sequence of Python `call` events for exactly these four "
    "tracked functions: `llamafactory.data.loader.get_dataset`, "
    "`llamafactory.data.loader._get_merged_dataset`, "
    "`llamafactory.data.loader._get_preprocessed_dataset`, and "
    "`llamafactory.data.loader._get_dataset_processor`. Include the entry event for the selected target "
    "invocation itself. After that entry, include a call to a listed function whenever it occurs while "
    "the selected target invocation remains on the Python call stack. Therefore listed direct calls and "
    "listed nested or transitive calls at any depth are included, even across unlisted intermediate "
    "functions; every call to a function outside the exact listed set, including builtins and "
    "comprehension frames, is excluded. End the sequence when the matching `return` event removes the "
    "selected target invocation from the stack. Preserve recursive and repeated call events as separate "
    "occurrences, with no sorting or deduplication. A generator or coroutine resumption counts only if "
    "Python emits a `call` event for that exact listed function, and every such event is a separate "
    "occurrence. Events are totally ordered by serial runtime emission order; timestamps are ignored and "
    "there is no secondary tie-breaker. Function identity is the full runtime dotted "
    "`module.Class.method` or `module.function` qualname (for example, `pkg.worker.Engine.run`). For each "
    "event, emit `file` as the POSIX repo-relative source path with no leading `./` (for example, "
    "`pkg/worker.py`) and emit `func` in that dotted identity format. Return exactly one JSON object "
    "with the single key `function_call_order`; its value is a JSON array of objects, and each object has "
    "exactly the two JSON string fields `file` and `func`, serialized in lexicographic key order "
    "(`file` then `func`). Array order is the chronological order defined above, and duplicates remain. "
    "No line numbers are emitted, so absolute-line, multi-line-statement, `def`, decorator, and docstring "
    "line conventions do not apply. No values other than paths and function identities are emitted, so "
    "`repr` versus `str`, exception-name, and empty-string-versus-JSON-null conventions do not apply."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/loader\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def read_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") in TRACKED_FUNCS:
            events.append((match.group("func"), match.group("event")))
    return events


def extract_call_order(events):
    invocation_number = 0
    selected = False
    completed = False
    target_depth = 0
    call_order = []

    for func, event in events:
        if event == "call" and func == TARGET_FUNC:
            invocation_number += 1
            if completed:
                continue
            if not selected and invocation_number == SELECTED_INVOCATION:
                selected = True
                target_depth = 1
                call_order.append({"file": TARGET_FILE, "func": func})
                continue
            if selected:
                target_depth += 1
                call_order.append({"file": TARGET_FILE, "func": func})
                continue

        if not selected or completed:
            continue

        if event == "call" and func in TRACKED_FUNCS:
            call_order.append({"file": TARGET_FILE, "func": func})
        elif event == "return" and func == TARGET_FUNC:
            target_depth -= 1
            if target_depth < 0:
                fail("selected target call-stack depth became negative")
            if target_depth == 0:
                completed = True

    target_call_count = sum(1 for func, event in events if func == TARGET_FUNC and event == "call")
    if target_call_count == 0:
        fail(f"trace contains zero call events for target function {TARGET_FUNC}")
    if target_call_count < SELECTED_INVOCATION:
        fail(
            f"trace contains only {target_call_count} target call event(s), "
            f"so invocation {SELECTED_INVOCATION} is absent"
        )
    if not selected:
        fail("selected target invocation was not found")
    if not completed:
        fail("selected target invocation has no matching frame-closing return event")
    if not call_order:
        fail("computed function call order is empty")

    observed_funcs = {item["func"] for item in call_order}
    missing = sorted(TRACKED_FUNCS - observed_funcs)
    if missing:
        fail(f"tracked functions have no call events inside the selected invocation: {missing}")
    return call_order


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = read_events(trace_path)
    if not events:
        fail("trace contains zero matching events for the target function and tracked callees")

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": extract_call_order(events)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
