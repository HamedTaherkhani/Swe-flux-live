#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/document_stores/in_memory/document_store.py"
TARGET_FILE_SUFFIX = "/" + TARGET_FILE
TARGET_FUNC = "haystack.document_stores.in_memory.document_store.InMemoryDocumentStore.write_documents"
TRACKED_FUNCS = (
    TARGET_FUNC,
    "haystack.document_stores.in_memory.document_store.InMemoryDocumentStore.delete_documents",
    "haystack.document_stores.in_memory.document_store.InMemoryDocumentStore._tokenize_bm25",
)
RUNTIME_TO_CANONICAL = {
    "haystack.document_stores.in_memory.document_store.write_documents": TRACKED_FUNCS[0],
    "haystack.document_stores.in_memory.document_store.delete_documents": TRACKED_FUNCS[1],
    "haystack.document_stores.in_memory.document_store._tokenize_bm25": TRACKED_FUNCS[2],
    TRACKED_FUNCS[0]: TRACKED_FUNCS[0],
    TRACKED_FUNCS[1]: TRACKED_FUNCS[1],
    TRACKED_FUNCS[2]: TRACKED_FUNCS[2],
}

QUESTION = (
    "Run the single pytest test "
    "`haystack_qa/document_store_write_documents_s6_calls/files/testcase.py::"
    "TestDocumentStoreLoadCallStructure::test_repeated_loads_with_mixed_documents`. "
    "During that test, consider invocations of "
    "`haystack.document_stores.in_memory.document_store.InMemoryDocumentStore.write_documents` in "
    "`haystack/document_stores/in_memory/document_store.py`. An invocation is one standard Python `call` trace event "
    "for that exact function during the test, numbered 1-based in the chronological order in which those events are "
    "observed; do not reorder or deduplicate invocations. For the second invocation, report the exact chronological "
    "sequence of `call` events for this tracked set of functions: "
    "`haystack.document_stores.in_memory.document_store.InMemoryDocumentStore.write_documents`, "
    "`haystack.document_stores.in_memory.document_store.InMemoryDocumentStore.delete_documents`, and "
    "`haystack.document_stores.in_memory.document_store.InMemoryDocumentStore._tokenize_bm25`. Start with the second "
    "target invocation's own `call` event. Then include a call to any function in the tracked set whenever it occurs "
    "while that invocation's frame remains on the call stack, whether the call is direct or nested/transitive; stop "
    "when that target invocation returns. Exclude every call outside the tracked set, including builtins and "
    "comprehension frames. Retain every repeated call as a separate array element. If a tracked generator were "
    "resumed and Python emitted another `call` event for that resumption, retain that event separately as well. Event "
    "order is the callback observation order in this synchronous test; no timestamp sorting or other tie-breaker is "
    "applied. Function identities use the full dotted `module.Class.method` qualname (for example, "
    "`sample.widgets.Widget.render`). For each event, emit `file` as the exact repo-relative POSIX path of the "
    "executing file and `func` in that dotted format. Runtime paths ending in the named repo-relative target path are "
    "therefore serialized exactly as `haystack/document_stores/in_memory/document_store.py`; no absolute paths or "
    "backslashes are emitted. Return exactly one JSON object with key `function_call_order`; its value is an array of "
    "objects, each with keys `file` then `func`, both JSON strings, in the event order just defined. Do not sort or "
    "deduplicate the array. There are no line numbers, values, exception names, `repr` strings, or null/empty-value "
    "conventions in this answer."
)

EVENT_RE = re.compile(
    r"\s(?P<file>\S+):(?P<line>\d+)\s+(?P<func>\S+)\s+"
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_call_order(trace_path):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    collecting = False
    completed_second = False
    call_order = []

    for raw_line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue

        runtime_file = match.group("file").replace("\\", "/")
        if not runtime_file.endswith(TARGET_FILE_SUFFIX):
            continue

        func = RUNTIME_TO_CANONICAL.get(match.group("func"), match.group("func"))
        event = match.group("event")
        if func == TARGET_FUNC:
            target_events += 1

        if event == "call" and func == TARGET_FUNC:
            invocation_number += 1
            if invocation_number == 2:
                if collecting or completed_second:
                    fail("invalid overlapping or repeated second target invocation")
                collecting = True

        if collecting and event == "call" and func in TRACKED_FUNCS:
            call_order.append({"file": TARGET_FILE, "func": func})

        if collecting and event == "return" and func == TARGET_FUNC:
            collecting = False
            completed_second = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < 2:
        fail(f"trace contains only {invocation_number} target call event(s); the second invocation is required")
    if collecting:
        fail("trace ended before the second target invocation returned")
    if not completed_second:
        fail("the second target invocation did not complete")
    if len(call_order) < 10:
        fail(f"call sequence is insufficiently rich: found only {len(call_order)} calls")

    observed_funcs = {item["func"] for item in call_order}
    missing_funcs = set(TRACKED_FUNCS) - observed_funcs
    if missing_funcs:
        fail(f"second invocation did not capture every tracked function: missing {sorted(missing_funcs)}")
    return call_order


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    call_order = parse_call_order(args.trace_log)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": call_order},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
