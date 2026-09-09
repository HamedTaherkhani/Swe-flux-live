import argparse
import json
from pathlib import Path
import re


TARGET_FILE = "sqlglot/executor/python.py"
TARGET_FUNC = "sqlglot.executor.python.PythonExecutor.aggregate"
TRACKED_FUNCS = {
    "sqlglot.executor.python.PythonExecutor._project_and_filter",
    "sqlglot.executor.python.PythonExecutor.aggregate",
    "sqlglot.executor.python.PythonExecutor.aggregate.<locals>.add_row",
    "sqlglot.executor.python.PythonExecutor.context",
    "sqlglot.executor.python.PythonExecutor.generate",
    "sqlglot.executor.python.PythonExecutor.generate_tuple",
    "sqlglot.executor.python.PythonExecutor.scan",
    "sqlglot.executor.python.PythonExecutor.table",
}
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/executor/python\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`sqlglot_qa/python_aggregate_s6_calls/files/testcase.py::"
    "TestPythonAggregateCalls::test_seeded_grouped_aggregation`. During the first "
    "invocation of the primary target "
    "`sqlglot.executor.python.PythonExecutor.aggregate` in "
    "`sqlglot/executor/python.py`, what is the exact chronological sequence of Python "
    "`call` events for this tracked set: "
    "`sqlglot.executor.python.PythonExecutor.aggregate`, "
    "`sqlglot.executor.python.PythonExecutor.generate_tuple`, "
    "`sqlglot.executor.python.PythonExecutor.generate`, "
    "`sqlglot.executor.python.PythonExecutor.table`, "
    "`sqlglot.executor.python.PythonExecutor.context`, "
    "`sqlglot.executor.python.PythonExecutor.aggregate.<locals>.add_row`, "
    "`sqlglot.executor.python.PythonExecutor.scan`, and "
    "`sqlglot.executor.python.PythonExecutor._project_and_filter`? An invocation is one "
    "Python `call` event for a function and invocations are numbered 1-based in "
    "chronological order. The requested interval starts with the `call` event that "
    "creates invocation 1 of the target and ends with its matching `return` event. "
    "Include the target's opening call and every call to an exact member of the tracked "
    "set that occurs while that target frame remains active, whether called directly "
    "from the target or nested/transitively through another frame. Exclude calls before "
    "or after that interval and all functions outside the exact set, including builtins "
    "and comprehension frames. Under Python tracing semantics, initial generator entry "
    "and each resumption after a yield each produce a `call` event; if this occurs for "
    "a tracked function in the interval, retain every event as a separate entry. Retain "
    "all repeated calls, preserve chronological event order, and do not sort or "
    "deduplicate. Function identity is the fully qualified dotted form "
    "`module.qualname`; for example, a method could be "
    "`sample.worker.Job.run`. For each call emit `file` as the forward-slash, "
    "repository-relative path and `func` in that dotted format. Return exactly a JSON "
    "object with key `function_call_order`; its value is a JSON array of objects, each "
    "with exactly the string keys `file` and `func`. Do not include line numbers, local "
    "values, or line, return, and exception events in the answer."
)


def compute_call_order(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_event_count = 0
    target_depth = 0
    started = False
    completed = False
    calls = []
    seen_funcs = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_event_count += 1

        if not started:
            if func != TARGET_FUNC or event != "call":
                continue
            started = True
            target_depth = 1
        elif func == TARGET_FUNC and event == "call":
            target_depth += 1

        if event == "call" and func in TRACKED_FUNCS:
            calls.append({"file": TARGET_FILE, "func": func})
            seen_funcs.add(func)

        if func == TARGET_FUNC and event == "return":
            target_depth -= 1
            if target_depth == 0:
                completed = True
                break

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not completed:
        raise RuntimeError("first target invocation has no matching return event")
    if not calls:
        raise RuntimeError("target interval contains zero tracked call events")
    if len(seen_funcs) < 2:
        raise RuntimeError("target interval contains calls for fewer than two tracked functions")

    return calls


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}],
        },
        "oracle_answer": {
            "function_call_order": compute_call_order(args.trace_log),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
