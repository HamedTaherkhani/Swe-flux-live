#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scrapy/core/engine.py"
TARGET_FUNC = "scrapy.core.engine.ExecutionEngine.open_spider_async"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "scrapy.core.engine.ExecutionEngine.needs_backout",
    "scrapy.core.engine.ExecutionEngine.pause",
    "scrapy.core.engine.ExecutionEngine.spider_is_idle",
    "scrapy.core.engine.ExecutionEngine.unpause",
    "scrapy.core.engine._Slot.__init__",
}

QUESTION = """Run the single pytest test `scrapy_qa/engine_open_spider_async_s6_calls/files/testcase.py::TestEngineOpenSpiderCallFlow::test_dynamic_signal_dispatch`. During the first and only logical coroutine invocation of `scrapy.core.engine.ExecutionEngine.open_spider_async` in `scrapy/core/engine.py`, what is the exact chronological sequence of Python `call` trace events for this tracked set of functions: `scrapy.core.engine.ExecutionEngine.open_spider_async`, `scrapy.core.engine.ExecutionEngine.needs_backout`, `scrapy.core.engine.ExecutionEngine.pause`, `scrapy.core.engine.ExecutionEngine.spider_is_idle`, `scrapy.core.engine.ExecutionEngine.unpause`, and `scrapy.core.engine._Slot.__init__`?

Here, a logical invocation is 1-based in chronological order and begins with the initial `call` event that enters a newly called function; the requested invocation is invocation 1. Its lifetime runs from that initial event through the coroutine's completion `return` event, inclusive; because this test makes only one logical target invocation, the completion event is the final `return` event for the target during the test. Earlier target `return` events that expose a pending awaited object are suspension events, not completion. A Python `call` event emitted when this same coroutine frame resumes after an `await` suspension is included as another sequence entry but does not begin a new logical invocation. Include calls to the listed functions whenever their `call` events occur during that lifetime, including the target's initial entry, its resumptions, and both direct and nested/transitive calls made while awaited work runs even when the target frame is suspended. Exclude every function outside the listed set, including builtins and comprehension frames. Preserve every repeated event; perform no deduplication. Order entries by the order in which Python delivers the trace events; that delivery order is also the tie-breaker for events observed at the same clock timestamp.

Function identity is the full dotted `module.qualname`, including the class for methods; for example, `scrapy.http.Request.replace`. The `file` value is the repository-relative POSIX path of the code object's source file. Return exactly one JSON object with key `function_call_order`. Its value is a JSON array of objects, each with exactly `file` (JSON string) and `func` (JSON string). Emit both strings directly, with no `repr()` or `str()` conversion. No sorting is applied beyond preserving the chronological order defined above."""

TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def parse_trace(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    target_events = []
    for ordinal, raw_line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines()
    ):
        match = TRACE_RE.search(raw_line)
        if not match:
            continue
        file_name = match.group("file").replace("\\", "/")
        if not file_name.endswith(TARGET_FILE):
            continue
        event = {
            "ordinal": ordinal,
            "line": int(match.group("line")),
            "func": match.group("func"),
            "event": match.group("event"),
        }
        events.append(event)
        if event["func"] == TARGET_FUNC:
            target_events.append(event)

    if not target_events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    initial_calls = [
        event
        for event in target_events
        if event["event"] == "call" and event["line"] == source_path_line(source_path)
    ]
    if len(initial_calls) != 1:
        raise RuntimeError(
            f"expected one initial call for {TARGET_FUNC}, found {len(initial_calls)}"
        )
    start_ordinal = initial_calls[0]["ordinal"]

    completion_returns = [
        event
        for event in target_events
        if event["event"] == "return"
        and event["ordinal"] >= start_ordinal
    ]
    if not completion_returns:
        raise RuntimeError(f"found no return events for {TARGET_FUNC}")
    end_ordinal = completion_returns[-1]["ordinal"]

    answer = [
        {"file": TARGET_FILE, "func": event["func"]}
        for event in events
        if start_ordinal <= event["ordinal"] <= end_ordinal
        and event["event"] == "call"
        and event["func"] in TRACKED_FUNCS
    ]
    if not answer:
        raise RuntimeError("computed function call order is unexpectedly empty")
    if len({entry["func"] for entry in answer}) < 2:
        raise RuntimeError("computed function call order has fewer than two functions")
    return {"function_call_order": answer}


def source_path_line(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionEngine":
            for child in node.body:
                if (
                    isinstance(child, ast.AsyncFunctionDef)
                    and child.name == "open_spider_async"
                ):
                    return child.lineno
    raise RuntimeError(f"target function not found in {source_path}")


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    oracle_answer = parse_trace(args.trace_log, source_path)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
