#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/data/parser.py"
TARGET_FUNC = "llamafactory.data.parser.get_dataset_list"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "llamafactory.data.parser.DatasetAttr.join",
    "llamafactory.data.parser.DatasetAttr.set_attr",
}
TRACE_FUNC_TO_IDENTITY = {
    TARGET_FUNC: TARGET_FUNC,
    "llamafactory.data.parser.join": "llamafactory.data.parser.DatasetAttr.join",
    "llamafactory.data.parser.set_attr": "llamafactory.data.parser.DatasetAttr.set_attr",
}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/parser_get_dataset_list_s6_calls/files/testcase.py::"
    "TestIndirectDatasetLoadingCallGraph::test_seeded_train_and_eval_dataset_loading`. During that "
    "run, consider the 2nd invocation of `llamafactory.data.parser.get_dataset_list` in "
    "`src/llamafactory/data/parser.py`. An invocation means one Python `call` trace event for that "
    "exact function during the complete test run; invocations are numbered 1-based in chronological "
    "runtime event order. Report `function_call_order`: the chronological sequence of Python `call` "
    "events for exactly these three tracked functions: "
    "`llamafactory.data.parser.get_dataset_list`, "
    "`llamafactory.data.parser.DatasetAttr.join`, and "
    "`llamafactory.data.parser.DatasetAttr.set_attr`. Include the entry `call` event for the selected "
    "target invocation itself, then include a call to a listed function whenever it occurs while "
    "that selected invocation remains on the Python call stack. Thus listed direct calls and listed "
    "nested or transitive calls at any depth are included even when unlisted intermediate functions "
    "are present; every call to a function outside the exact listed set, including builtins and "
    "comprehension frames, is excluded. End the sequence when the matching `return` event removes "
    "the selected target invocation from the stack. Preserve repeated and recursive calls as "
    "separate occurrences, with no sorting or deduplication. A generator or coroutine resumption "
    "counts only when Python emits a `call` event for that exact listed function, and every such "
    "event is a separate occurrence. Events are totally ordered by their serial runtime emission "
    "order; timestamps are ignored and there is no secondary tie-breaker. Function identity is the "
    "full runtime dotted `module.Class.method` or `module.function` qualname (for example, "
    "`pkg.worker.Engine.run`). For each event, emit `file` as the POSIX repo-relative source path "
    "with no leading `./` (for example, `pkg/worker.py`) and `func` in that dotted identity format. "
    "Return exactly one JSON object with the single key `function_call_order`, whose value is a JSON "
    "array of objects. Each array object has exactly two JSON string fields, serialized in "
    "lexicographic key order as `file` then `func`; array order is the chronological order defined "
    "above and duplicates remain. No line numbers are emitted, so def/decorator/docstring and "
    "multi-line-statement line conventions do not apply. No values other than paths and function "
    "identities are emitted, so `repr` versus `str`, exception-name, and empty-versus-null "
    "conventions do not apply."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/parser\.py):(?P<line>\d+) "
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
        if match:
            canonical_func = TRACE_FUNC_TO_IDENTITY.get(match.group("func"))
            if canonical_func is not None:
                events.append((canonical_func, match.group("event")))
    return events


def extract_second_call_order(events):
    invocation_number = 0
    selected = False
    completed = False
    selected_target_depth = 0
    call_order = []

    for func, event in events:
        if event == "call" and func == TARGET_FUNC:
            invocation_number += 1
            if completed:
                continue
            if not selected and invocation_number == 2:
                selected = True
                selected_target_depth = 1
                call_order.append({"file": TARGET_FILE, "func": func})
                continue
            if selected:
                selected_target_depth += 1
                call_order.append({"file": TARGET_FILE, "func": func})
                continue

        if not selected or completed:
            continue

        if event == "call" and func in TRACKED_FUNCS:
            call_order.append({"file": TARGET_FILE, "func": func})
        elif event == "return" and func == TARGET_FUNC:
            selected_target_depth -= 1
            if selected_target_depth < 0:
                fail("selected target call-stack depth became negative")
            if selected_target_depth == 0:
                completed = True

    target_events = [event for func, event in events if func == TARGET_FUNC]
    if not target_events:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if invocation_number < 2:
        fail(f"trace contains only {invocation_number} target call event(s), so invocation 2 is absent")
    if not selected:
        fail("the second target invocation was not selected")
    if not completed:
        fail("the second target invocation has no matching frame-closing return event")
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
        fail("trace contains zero matching events in the target file")

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": extract_second_call_order(events)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
