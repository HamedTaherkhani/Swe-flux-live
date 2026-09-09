#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/data/template.py"
TARGET_FUNC = "llamafactory.data.template.get_template_and_fix_tokenizer"
TRACKED_FUNCS = {
    "llamafactory.data.template.Template._add_or_replace_eos_token",
    "llamafactory.data.template.Template._convert_slots_to_jinja",
    "llamafactory.data.template.Template._convert_slots_to_ollama",
    "llamafactory.data.template.Template._get_jinja_template",
    "llamafactory.data.template.Template._jinja_escape",
    "llamafactory.data.template.Template.fix_jinja_template",
    "llamafactory.data.template.Template.fix_special_tokens",
    "llamafactory.data.template.get_template_and_fix_tokenizer",
    "llamafactory.data.template.parse_template",
    "llamafactory.data.template.parse_template.<locals>.find_diff",
}
TRACE_NAME_TO_FUNC = {
    "_add_or_replace_eos_token": "llamafactory.data.template.Template._add_or_replace_eos_token",
    "_convert_slots_to_jinja": "llamafactory.data.template.Template._convert_slots_to_jinja",
    "_convert_slots_to_ollama": "llamafactory.data.template.Template._convert_slots_to_ollama",
    "_get_jinja_template": "llamafactory.data.template.Template._get_jinja_template",
    "_jinja_escape": "llamafactory.data.template.Template._jinja_escape",
    "find_diff": "llamafactory.data.template.parse_template.<locals>.find_diff",
    "fix_jinja_template": "llamafactory.data.template.Template.fix_jinja_template",
    "fix_special_tokens": "llamafactory.data.template.Template.fix_special_tokens",
    "get_template_and_fix_tokenizer": "llamafactory.data.template.get_template_and_fix_tokenizer",
    "parse_template": "llamafactory.data.template.parse_template",
}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/template_get_template_and_fix_tokenizer_m6_calls/files/testcase.py::"
    "TestIndirectTemplateCallGraph::test_seeded_engine_construction`. The primary target is "
    "`llamafactory.data.template.get_template_and_fix_tokenizer` in "
    "`src/llamafactory/data/template.py` (its definition begins at line 506). Report "
    "`covered_functions` for exactly this tracked set, all from that file: "
    "`llamafactory.data.template.Template._add_or_replace_eos_token`, "
    "`llamafactory.data.template.Template._convert_slots_to_jinja`, "
    "`llamafactory.data.template.Template._convert_slots_to_ollama`, "
    "`llamafactory.data.template.Template._get_jinja_template`, "
    "`llamafactory.data.template.Template._jinja_escape`, "
    "`llamafactory.data.template.Template.fix_jinja_template`, "
    "`llamafactory.data.template.Template.fix_special_tokens`, "
    "`llamafactory.data.template.get_template_and_fix_tokenizer`, "
    "`llamafactory.data.template.parse_template`, and "
    "`llamafactory.data.template.parse_template.<locals>.find_diff`. A tracked function is "
    "covered exactly when Python begins at least one invocation of that exact function during "
    "the complete test run (equivalently, when an instrumentation callback for Python function "
    "entry would receive a `call` event for it). An invocation is one such function-entry event, "
    "and invocations are 1-based in chronological order when reasoning about the run, although "
    "invocation numbers are not emitted. Apply this rule to tracked calls anywhere in the test: "
    "include direct calls made by a listed function's frame, transitive calls while that frame "
    "is on the stack, and tracked calls made before or after a primary-target invocation. Ignore "
    "builtins and every function outside the listed set. Repeated calls, recursion, and repeated "
    "generator or coroutine resumptions count as separate entry events if Python emits separate "
    "`call` events, but coverage is set membership: deduplicate them to exactly one object per "
    "exact function identity. Emit only covered tracked functions, with no placeholder for an "
    "uncovered function. Function identity is the full runtime dotted `module.qualname`, "
    "including `<locals>` for a nested function; for example, `pkg.worker.Engine.run`. For each "
    "object, `file` is the POSIX repo-relative source path without a leading `./` (for example, "
    "`pkg/worker.py`), and `func` is that full dotted identity. Sort the deduplicated output in "
    "ascending lexicographic order by the complete two-key tuple (`file`, `func`), comparing JSON "
    "string values by Unicode code-point order; that tuple is the complete tie-break rule, not "
    "call chronology. Return exactly one JSON object with the single key `covered_functions`; "
    "its value is a JSON array, and every array element has exactly the two JSON string fields "
    "`file` and `func`. There are no counts or invocation numbers in the output. No `repr` versus "
    "`str`, null/empty-value, exception-name, or line-number serialization convention applies, "
    "because every answer leaf is one of the source-path or function-identity JSON strings just "
    "defined."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/template\.py):(?P<line>\d+) "
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
            code_name = match.group("func").rpartition(".")[2]
            canonical_func = TRACE_NAME_TO_FUNC.get(code_name)
            if canonical_func is not None:
                events.append((canonical_func, match.group("event")))
    return events


def compute_covered(events):
    target_events = [event for func, event in events if func == TARGET_FUNC]
    if not target_events:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if "call" not in target_events:
        fail(f"trace contains zero call events for target function {TARGET_FUNC}")

    called = {func for func, event in events if event == "call" and func in TRACKED_FUNCS}
    if not called:
        fail("computed covered function set is empty")
    return sorted(
        ({"file": TARGET_FILE, "func": func} for func in called),
        key=lambda item: (item["file"], item["func"]),
    )


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
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_functions": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"covered_functions": compute_covered(events)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
