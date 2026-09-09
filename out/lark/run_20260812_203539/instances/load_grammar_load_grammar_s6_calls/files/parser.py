#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TARGET_FILE_SUFFIX = "/lark/load_grammar.py"
TARGET_FILE = "lark/load_grammar.py"
TARGET_FUNC = "lark.load_grammar.GrammarBuilder.load_grammar"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "lark.load_grammar._parse_grammar",
    "lark.load_grammar.GrammarBuilder._unpack_import",
    "lark.load_grammar.GrammarBuilder.do_import",
    "lark.load_grammar._get_mangle.<locals>.mangle",
    "lark.load_grammar.GrammarBuilder._unpack_definition",
    "lark.load_grammar.GrammarBuilder._define",
    "lark.load_grammar.GrammarBuilder._extend",
    "lark.load_grammar.GrammarBuilder._ignore",
    "lark.load_grammar.resolve_term_references",
}

QUESTION = (
    "Run only the pytest test "
    "`lark_qa/load_grammar_load_grammar_s6_calls/files/testcase.py::"
    "TestGeneratedGrammarImports::test_seeded_import_and_directive_mix`. "
    "For the first invocation of "
    "`lark.load_grammar.GrammarBuilder.load_grammar` in "
    "`lark/load_grammar.py`, what is the exact chronological sequence of "
    "Python `sys.settrace` `call` events for this tracked set of functions: "
    "`lark.load_grammar.GrammarBuilder.load_grammar`, "
    "`lark.load_grammar._parse_grammar`, "
    "`lark.load_grammar.GrammarBuilder._unpack_import`, "
    "`lark.load_grammar.GrammarBuilder.do_import`, "
    "`lark.load_grammar._get_mangle.<locals>.mangle`, "
    "`lark.load_grammar.GrammarBuilder._unpack_definition`, "
    "`lark.load_grammar.GrammarBuilder._define`, "
    "`lark.load_grammar.GrammarBuilder._extend`, "
    "`lark.load_grammar.GrammarBuilder._ignore`, and "
    "`lark.load_grammar.resolve_term_references`? "
    "An invocation is one `call` event for the target during this test run, "
    "and invocations are numbered from 1 in chronological order. The interval "
    "for invocation 1 starts with its opening `call` event and ends with its "
    "matching `return` event. Include that opening target call itself and every "
    "`call` event for a function in the tracked set whenever invocation 1 is "
    "on the stack, including calls made directly by its frame and calls made "
    "transitively by nested functions. Thus a recursively or indirectly nested "
    "target invocation is included, and its events do not end the outer "
    "interval. Exclude calls outside the tracked set, including builtins, "
    "comprehension frames, and other repository functions. Preserve every "
    "repeated call. If a tracked generator were resumed and Python emitted "
    "another `call` event for that resumption, count it as another item. Order "
    "items solely by chronological `call`-event delivery; do not sort or "
    "deduplicate them. The test is single-threaded, so no tie-breaker is "
    "needed. Function identity is the defining module plus Python code-object "
    "qualified name, in `module.Class.method` or `module.function` form (for "
    "example, `lark.parsers.lalr_parser.Parser.parse`); retain `<locals>` in a "
    "nested function's qualified name. Return exactly a JSON object with the "
    "single key `function_call_order`. Its value is a list of objects, each "
    "with exactly two string fields: `file` and `func`. For every item, `file` "
    "is the forward-slash repo-relative defining path "
    "`lark/load_grammar.py`, and `func` is the function identity just defined. "
    "Do not apply `repr()` or `str()` wrappers to either string."
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
