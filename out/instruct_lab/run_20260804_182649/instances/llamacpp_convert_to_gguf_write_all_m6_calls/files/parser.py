#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/llamacpp/llamacpp_convert_to_gguf.py"
MODULE = "instructlab.llamacpp.llamacpp_convert_to_gguf"
TARGET_FUNC = f"{MODULE}.OutputFile.write_all"
TRACKED_FUNCS = {
    f"{MODULE}.BpeVocab.added_tokens",
    f"{MODULE}.BpeVocab.all_tokens",
    f"{MODULE}.BpeVocab.bpe_tokens",
    f"{MODULE}.OutputFile.__init__",
    f"{MODULE}.OutputFile.add_meta_arch",
    f"{MODULE}.OutputFile.add_meta_special_vocab",
    f"{MODULE}.OutputFile.add_meta_vocab",
    f"{MODULE}.OutputFile.add_tensor_info",
    f"{MODULE}.OutputFile.close",
    f"{MODULE}.OutputFile.do_item",
    f"{MODULE}.OutputFile.extract_vocabulary_from_model",
    f"{MODULE}.OutputFile.handle_tokenizer_model",
    f"{MODULE}.OutputFile.maybe_do_quantize",
    f"{MODULE}.OutputFile.write_all",
    f"{MODULE}.OutputFile.write_meta",
    f"{MODULE}.OutputFile.write_tensor_info",
    f"{MODULE}.OutputFile.write_vocab_only",
    f"{MODULE}.Q8_0QuantizedDataType.quantize",
    f"{MODULE}.SentencePieceVocab.all_tokens",
    f"{MODULE}.bounded_parallel_map",
    f"{MODULE}.check_vocab_size",
    f"{MODULE}.convert_llama_to_gguf",
}
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def covered_functions(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    covered: set[str] = set()
    target_events = 0
    target_calls = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        file_name = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if not file_name.endswith("/" + TARGET_FILE):
            continue
        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_calls += 1
        if event == "call" and func in TRACKED_FUNCS:
            covered.add(func)

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains no call event for target function {TARGET_FUNC}")
    if not covered:
        fail("trace contains no covered function from the tracked set")

    return [
        {"file": TARGET_FILE, "func": func}
        for func in sorted(covered)
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = {"covered_functions": covered_functions(Path(args.trace_log))}
    tracked_text = ", ".join(f"`{func}`" for func in sorted(TRACKED_FUNCS))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/llamacpp_convert_to_gguf_write_all_m6_calls/files/"
        "testcase.py::TestLlamaCppConversionCallGraph::"
        "test_programmatic_model_conversion` against this repository. Considering "
        "the target function "
        "`instructlab.llamacpp.llamacpp_convert_to_gguf.OutputFile.write_all` in "
        "`src/instructlab/llamacpp/llamacpp_convert_to_gguf.py`, which functions "
        "in the following exact tracked set execute at least once during the entire "
        f"named test run: {tracked_text}? "
        "A function executes when Python emits a runtime call event whose active "
        "frame has exactly that tracked function identity. Count such an event "
        "regardless of which frame made the call: direct calls, transitive calls, "
        "and calls that occur before, during, or after the target frame all qualify "
        "if they occur within the named test. Calls to builtins, mocks, callable "
        "objects, comprehension frames, or any other function outside the exact "
        "tracked set do not qualify. An invocation is one call event, counted "
        "1-based in chronological order from the start of the test; however, the "
        "answer records only whether its function was invoked at least once, not "
        "the invocation number or count. Repeated calls and recursive calls therefore "
        "produce only one output entry per function. For a generator, both its first "
        "entry and each later resumption may produce call events; any one of those "
        "events is sufficient for coverage, and all are deduplicated into that same "
        "single entry. A function identity is the fully qualified dotted "
        "`module.qualname` from the executing frame, for example "
        "`package.module.ExampleClass.example_method`; do not use a bare name or "
        "prefix it with `src`. "
        "Return exactly one JSON object with key `covered_functions`. Its value is "
        "a JSON array containing only covered members of the tracked set; omit every "
        "member with zero qualifying call events. Each array entry has exactly the "
        "keys `file` then `func`, both JSON strings. `file` is the repo-relative "
        "POSIX path shown above and `func` is the exact fully qualified identity. "
        "Deduplicate by the pair (`file`, `func`), then sort in ascending "
        "lexicographic Unicode-code-point order first by `file` and then by `func`; "
        "this is the output order, independent of call chronology. Serialize using "
        "ordinary JSON string syntax, not Python `repr`; no entry contains null, an "
        "empty string, or an omitted key."
    )
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": question,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
