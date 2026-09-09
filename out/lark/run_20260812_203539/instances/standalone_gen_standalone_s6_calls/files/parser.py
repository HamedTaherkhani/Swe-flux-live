#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TARGET_FILE_SUFFIX = "/lark/tools/standalone.py"
TARGET_FILE = "lark/tools/standalone.py"
TARGET_FUNC = "lark.tools.standalone.gen_standalone"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "lark.tools.standalone.gen_standalone.<locals>.compressed_output",
    "lark.tools.standalone.gen_standalone.<locals>.output_decompress",
    "lark.tools.standalone.extract_sections",
    "lark.tools.standalone.strip_docstrings",
}

QUESTION = (
    "Run only the pytest test "
    "`lark_qa/standalone_gen_standalone_s6_calls/files/testcase.py::"
    "TestStandaloneCommand::test_seeded_compressed_generation`. During that "
    "test, consider the first invocation of "
    "`lark.tools.standalone.gen_standalone` defined in "
    "`lark/tools/standalone.py`. What is the exact chronological sequence of "
    "Python `sys.settrace` `call` events for this tracked set of functions: "
    "`lark.tools.standalone.gen_standalone`, "
    "`lark.tools.standalone.gen_standalone.<locals>.compressed_output`, "
    "`lark.tools.standalone.gen_standalone.<locals>.output_decompress`, "
    "`lark.tools.standalone.extract_sections`, and "
    "`lark.tools.standalone.strip_docstrings`? "
    "An invocation is one `call` event for the target during this test run, "
    "and target invocations are numbered from 1 in chronological order. The "
    "interval for invocation 1 begins with its opening `call` event and ends "
    "with its matching `return` event. Include the opening target call itself "
    "and every `call` event for a function in the tracked set whenever "
    "invocation 1 is on the stack, whether called directly from the target "
    "frame or transitively from a nested frame. A nested target invocation, "
    "if any, is included and does not end the outer interval. Exclude every "
    "call outside the tracked set, including builtins, comprehension frames, "
    "and other repository functions. Preserve repeated calls. If a tracked "
    "generator is resumed and Python emits another `call` event for that "
    "resumption, include another item. Order items solely by chronological "
    "`call`-event delivery; do not sort or deduplicate. The test is "
    "single-threaded, so no tie-breaker is needed. Function identity is the "
    "defining module plus the Python code object's qualified name, in "
    "`module.Class.method` or `module.function` form (for example, "
    "`package.worker.Engine.run`); retain `<locals>` for nested functions. "
    "Return exactly a JSON object with the single key `function_call_order`. "
    "Its value is a JSON list of objects, each with exactly two string fields "
    "named `file` and `func`. In every item, `file` is the forward-slash, "
    "repo-relative defining path `lark/tools/standalone.py`, and `func` is "
    "the function identity defined above. Emit the strings directly as JSON "
    "strings, without applying Python `repr()` or `str()` wrappers."
)


def parse_event(raw_line):
    marker = " event="
    if marker not in raw_line:
        return None

    left, event_tail = raw_line.split(marker, 1)
    parts = left.rsplit(" ", 2)
    if len(parts) != 3:
        raise ValueError(f"malformed trace event prefix: {raw_line!r}")
    _, location, func = parts
    try:
        filename, line_text = location.rsplit(":", 1)
        int(line_text)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"malformed trace event location: {raw_line!r}") from exc

    event = event_tail.split(" ", 1)[0]
    return filename.replace("\\", "/"), func, event


def compute_call_order(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    target_events = 0
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_event(raw_line)
        if parsed is None:
            continue
        filename, func, event = parsed
        if not filename.endswith(TARGET_FILE_SUFFIX):
            continue
        if func == TARGET_FUNC:
            target_events += 1
        if func in TRACKED_FUNCS:
            events.append((func, event))

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    started = False
    finished = False
    target_depth = 0
    call_order = []
    for func, event in events:
        if not started:
            if func != TARGET_FUNC or event != "call":
                continue
            started = True
            target_depth = 1
            call_order.append({"file": TARGET_FILE, "func": func})
            continue

        if event == "call":
            call_order.append({"file": TARGET_FILE, "func": func})
            if func == TARGET_FUNC:
                target_depth += 1
        elif event == "return" and func == TARGET_FUNC:
            target_depth -= 1
            if target_depth == 0:
                finished = True
                break

    if not started:
        raise RuntimeError(f"no call event found for {TARGET_FUNC}")
    if not finished:
        raise RuntimeError(f"first invocation of {TARGET_FUNC} did not return")
    if not call_order:
        raise RuntimeError("computed call order is empty")
    if len({item["func"] for item in call_order}) < 2:
        raise RuntimeError("call order contains fewer than two tracked functions")
    return call_order


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    call_order = compute_call_order(args.trace_log)
    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, sort_keys=True))


if __name__ == "__main__":
    main()

