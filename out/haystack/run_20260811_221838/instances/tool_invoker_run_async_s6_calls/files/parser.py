#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "haystack/components/tools/tool_invoker.py"
RAW_MODULE = "haystack.components.tools.tool_invoker"
TARGET_FUNC = RAW_MODULE + ".ToolInvoker.run_async"
TRACKED_FUNCS = {
    TARGET_FUNC,
    RAW_MODULE + ".ToolInvoker._get_func_params",
    RAW_MODULE + ".ToolInvoker._handle_error",
    RAW_MODULE + ".ToolInvoker._inject_state_args",
    RAW_MODULE + ".ToolInvoker._prepare_tool_call_params",
    RAW_MODULE + ".ToolInvoker._validate_and_prepare_tools",
}
CANONICAL_PREFIX = RAW_MODULE + ".ToolInvoker."

QUESTION = """Run the single pytest test `haystack_qa/tool_invoker_run_async_s6_calls/files/testcase.py::TestToolInvokerAsyncCalls::test_seeded_parallel_tool_batch`. During that test, consider the first invocation of `haystack.components.tools.tool_invoker.ToolInvoker.run_async` in `haystack/components/tools/tool_invoker.py`. An invocation is one Python `call` event beginning execution or resumption of that function's frame; invocations are numbered from 1 in chronological order. For this async function, the first invocation ends at its first matching Python `return` event, including a `return` event caused by suspension at an `await`; do not continue into a later coroutine-resumption `call` event.

Report the exact ordered sequence of Python `call` events for this tracked set: `haystack.components.tools.tool_invoker.ToolInvoker.run_async`, `haystack.components.tools.tool_invoker.ToolInvoker._validate_and_prepare_tools`, `haystack.components.tools.tool_invoker.ToolInvoker._prepare_tool_call_params`, `haystack.components.tools.tool_invoker.ToolInvoker._handle_error`, `haystack.components.tools.tool_invoker.ToolInvoker._inject_state_args`, and `haystack.components.tools.tool_invoker.ToolInvoker._get_func_params`. Include the `call` event that starts the first target invocation itself, then include every call to a listed function made while that invocation is active, whether directly from the target frame or transitively through nested calls. Stop immediately after the matching return event that ends this invocation. Exclude calls before it starts or after it ends, every function outside the listed set, builtins, and comprehension frames. Retain every repeated call without deduplication. A generator or coroutine resumption produces another `call` event and would be retained if it occurs before the invocation-ending return; a resumption after that return is outside the requested interval.

Return exactly `{"function_call_order": [{"file": "...", "func": "..."}]}`. `function_call_order` is a JSON list in chronological call-event order; do not sort or deduplicate it. Execution in the requested interval is serial and therefore supplies a total order, so no secondary tie-breaker applies. Each item has exactly two JSON string fields in the displayed key order. `file` is the called function's repository-relative POSIX source path with no leading `./`. `func` is the full dotted identity in `module.Class.method` or `module.function` form; for example, `package.processing.cleaner.TextCleaner.run`. Do not emit a bare name or omit the module. The class that owns the function in repository source determines the `Class` segment even if runtime code-object metadata omits it. Both fields always contain strings, so no `repr()`/`str()` value conversion, missing-value representation, JSON `null`, exception-name, or line-number convention applies."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?: |$)"
)


def canonical_func(raw_func: str) -> str:
    if not raw_func.startswith(RAW_MODULE + "."):
        return raw_func
    method_name = raw_func.rsplit(".", 1)[1]
    candidate = CANONICAL_PREFIX + method_name
    return candidate if candidate in TRACKED_FUNCS else raw_func


def harvest(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    started = False
    completed = False
    call_order: list[dict[str, str]] = []

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match:
                continue

            func = canonical_func(match.group("func"))
            event = match.group("event")
            if func == TARGET_FUNC:
                target_events += 1

            if not started:
                if event != "call" or func != TARGET_FUNC:
                    continue
                target_calls += 1
                started = True

            if event == "call" and func in TRACKED_FUNCS:
                absolute_file = match.group("file").replace("\\", "/")
                if not absolute_file.endswith("/" + TARGET_FILE):
                    raise ValueError(f"tracked call came from an unexpected file: {absolute_file}")
                call_order.append({"file": TARGET_FILE, "func": func})

            if started and event == "return" and func == TARGET_FUNC:
                completed = True
                break

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if not completed:
        raise ValueError("trace ended before the first target invocation returned or suspended")
    if len(call_order) < 10:
        raise ValueError(f"call order is unexpectedly short: {len(call_order)} events")
    if len({item["func"] for item in call_order}) < 2:
        raise ValueError("call order contains fewer than two distinct tracked functions")
    return call_order


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    call_order = harvest(Path(args.trace_log))
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": call_order},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
