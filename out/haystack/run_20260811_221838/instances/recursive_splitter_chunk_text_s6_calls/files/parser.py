#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "haystack/components/preprocessors/recursive_splitter.py"
TARGET_FUNC = "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_text"
TRACKED_FUNCS = {
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._apply_overlap",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_length",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_text",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._create_chunk_starting_with_overlap",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._fall_back_to_fixed_chunking",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._get_overlap",
    "haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._split_chunk",
}
RAW_MODULE = "haystack.components.preprocessors.recursive_splitter"
CANONICAL_PREFIX = RAW_MODULE + ".RecursiveDocumentSplitter."

QUESTION = """Run the single pytest test `haystack_qa/recursive_splitter_chunk_text_s6_calls/files/testcase.py::TestRecursiveSplitterCalls::test_generated_hierarchical_document`. During that run, consider the first invocation of `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_text` in `haystack/components/preprocessors/recursive_splitter.py`. An invocation is one Python `call` event that begins execution of that function's frame; invocations are numbered from 1 in chronological order.

Report the exact ordered sequence of Python `call` events for this tracked set of functions: `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_text`, `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._chunk_length`, `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._fall_back_to_fixed_chunking`, `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._apply_overlap`, `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._get_overlap`, `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._create_chunk_starting_with_overlap`, and `haystack.components.preprocessors.recursive_splitter.RecursiveDocumentSplitter._split_chunk`. Include the `call` event that starts the first target invocation itself, then include every call to a listed function whenever that first invocation remains on the call stack, whether the call is direct or occurs transitively through nested and recursive calls. Stop after the matching return from that first invocation. Exclude calls before it starts or after it returns, calls to every function not in the listed set, builtins, and comprehension frames. Retain every repeated call without deduplication. If any listed function were a generator, each generator-resumption `call` event would be retained as a separate event.

Return exactly `{"function_call_order": [{"file": "...", "func": "..."}]}`. `function_call_order` is a JSON list in the chronological order in which the call events occur; do not sort or deduplicate it. Serial Python execution gives the total order, so no secondary tie-breaker applies. Each list item has exactly two JSON string fields in the displayed key order. `file` is the repository-relative POSIX path of the called function's source file, with no leading `./`. `func` is the full dotted function identity in `module.Class.method` or `module.function` form; for example, `package.preprocessing.cleaner.TextCleaner.run`. Do not use a bare name or omit the module. Function ownership in the repository source determines the `Class` segment, even if runtime code-object metadata omits that segment. No value formatting with `repr()`, line-number convention, missing-value convention, or JSON `null` convention applies because both fields always contain strings."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?: |$)"
)


def harvest(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    target_invocations = 0
    active_target_depth = 0
    started = False
    completed = False
    call_order = []

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match:
                continue

            raw_func = match.group("func")
            if raw_func.startswith(RAW_MODULE + "."):
                method_name = raw_func.rsplit(".", 1)[1]
                candidate = CANONICAL_PREFIX + method_name
                func = candidate if candidate in TRACKED_FUNCS else raw_func
            else:
                func = raw_func
            event = match.group("event")
            if func == TARGET_FUNC:
                target_events += 1

            if event == "call" and func == TARGET_FUNC:
                target_invocations += 1
                if not started:
                    started = True
                    active_target_depth = 1
                elif active_target_depth:
                    active_target_depth += 1

            if started and active_target_depth and event == "call" and func in TRACKED_FUNCS:
                absolute_file = match.group("file").replace("\\", "/")
                if not absolute_file.endswith("/" + TARGET_FILE):
                    raise ValueError(f"tracked call came from an unexpected file: {absolute_file}")
                call_order.append({"file": TARGET_FILE, "func": func})

            if started and active_target_depth and event == "return" and func == TARGET_FUNC:
                active_target_depth -= 1
                if active_target_depth == 0:
                    completed = True
                    break

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if target_invocations == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if not completed:
        raise ValueError("trace ended before the first target invocation returned")
    if not call_order:
        raise ValueError("the first target invocation produced an empty call order")
    observed_funcs = {item["func"] for item in call_order}
    if len(observed_funcs) < 2:
        raise ValueError("the call order contains fewer than two distinct tracked functions")
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
