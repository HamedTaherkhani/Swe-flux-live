#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/model/loader.py"
TARGET_FUNC = "llamafactory.model.loader.load_model"
TRACKED_FUNCS = {
    "llamafactory.model.loader._get_init_kwargs",
    "llamafactory.model.loader.load_config",
    TARGET_FUNC,
}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/loader_load_model_s6_calls/files/testcase.py::"
    "TestIndirectModelLoadingCallGraph::test_seeded_recursive_inference_loading`. During that run, "
    "consider the 1st invocation of `llamafactory.model.loader.load_model` in "
    "`src/llamafactory/model/loader.py`. An invocation means one Python `call` trace event for that "
    "exact function during the complete test run, numbered 1-based in chronological event order. "
    "Report `function_call_order`: the chronological sequence of Python `call` events for exactly "
    "these three tracked functions: `llamafactory.model.loader.load_model`, "
    "`llamafactory.model.loader.load_config`, and "
    "`llamafactory.model.loader._get_init_kwargs`. Include such an event whenever it occurs while "
    "the 1st target invocation is on the call stack: include the entry event for that target "
    "invocation itself, direct calls, and nested/transitive calls at any depth through any "
    "intermediate function. Exclude every call to a function outside the listed set. Preserve every "
    "repeated event with no deduplication or sorting. A generator or coroutine resumption counts "
    "only if Python emits a `call` event for it, and each such event is a separate occurrence. The "
    "sequence ends when the matching `return` event removes the 1st target invocation from the "
    "stack. Events are totally ordered by their serial runtime emission order; no timestamp or "
    "secondary tie-breaker is used. Function identity is the full runtime dotted "
    "`module.Class.method` or `module.function` qualname (for example, "
    "`pkg.worker.Engine.run`). For each event, emit `file` as the POSIX repo-relative source path "
    "with no leading `./` (for example, `pkg/worker.py`) and `func` in that dotted identity format. "
    "Return exactly one JSON object with the single key `function_call_order`, whose value is a "
    "JSON array of objects. Every array object has exactly two JSON string fields, ordered "
    "lexicographically as `file` then `func`. Array order is the chronological order defined above; "
    "duplicates remain. No `repr`/`str` value formatting, null convention, or line-number convention "
    "applies because the answer contains only source paths and function identities."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/model/loader\.py):(?P<line>\d+) "
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
            events.append((match.group("func"), match.group("event")))
    return events


def extract_call_order(events):
    started = False
    completed = False
    target_depth = 0
    call_order = []

    for func, event in events:
        if event == "call" and func == TARGET_FUNC:
            if completed:
                continue
            if not started:
                started = True
            target_depth += 1
            call_order.append({"file": TARGET_FILE, "func": func})
            continue

        if not started or completed:
            continue

        if event == "call" and func in TRACKED_FUNCS:
            call_order.append({"file": TARGET_FILE, "func": func})
        elif event == "return" and func == TARGET_FUNC:
            target_depth -= 1
            if target_depth < 0:
                fail("target call-stack depth became negative")
            if target_depth == 0:
                completed = True

    if not started:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if not completed:
        fail("the first target invocation has no matching frame-closing return event")
    if not call_order:
        fail("computed function call order is empty")
    observed_funcs = {item["func"] for item in call_order}
    missing = sorted(TRACKED_FUNCS - observed_funcs)
    if missing:
        fail(f"tracked functions have no calls inside the selected invocation: {missing}")
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
        fail(f"trace contains zero events for {TARGET_FUNC}")
    answer = {"function_call_order": extract_call_order(events)}
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
