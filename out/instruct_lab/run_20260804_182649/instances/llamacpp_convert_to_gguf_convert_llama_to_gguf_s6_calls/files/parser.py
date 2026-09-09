#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/llamacpp/llamacpp_convert_to_gguf.py"
MODULE = "instructlab.llamacpp.llamacpp_convert_to_gguf"
TARGET_FUNC = f"{MODULE}.convert_llama_to_gguf"
INVOCATION = 2
TRACKED_FUNCS = (
    TARGET_FUNC,
    f"{MODULE}.convert_model_names",
    f"{MODULE}.permute_lazy",
    f"{MODULE}.pick_output_type",
    f"{MODULE}.convert_to_output_type",
    f"{MODULE}.GGMLFileType.type_for_tensor",
    f"{MODULE}.LazyTensor.astype",
    f"{MODULE}.LazyTensor.validate_conversion_to",
    f"{MODULE}.default_outfile",
)
TRACKED_SET = set(TRACKED_FUNCS)
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test `instruct_lab_qa/llamacpp_convert_to_gguf_convert_llama_to_gguf_s6_calls/files/testcase.py::TestLlamaCppConversionCalls::test_second_seeded_simple_train_conversion`. During its complete run, consider the second invocation of `instructlab.llamacpp.llamacpp_convert_to_gguf.convert_llama_to_gguf` in the repo-relative POSIX file `src/instructlab/llamacpp/llamacpp_convert_to_gguf.py`. What is the exact ordered sequence of calls to the following tracked functions?

- `instructlab.llamacpp.llamacpp_convert_to_gguf.convert_llama_to_gguf`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.convert_model_names`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.permute_lazy`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.pick_output_type`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.convert_to_output_type`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.GGMLFileType.type_for_tensor`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.LazyTensor.astype`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.LazyTensor.validate_conversion_to`
- `instructlab.llamacpp.llamacpp_convert_to_gguf.default_outfile`

An invocation is one Python `call` trace event for the target function, counted 1-based in chronological order over the complete test run. Select the interval beginning with the target's second `call` event and ending with its matching `return` event. Include that opening target call itself. While that target invocation is on the call stack, include every `call` event whose function identity is exactly one of the nine names listed above, whether the call is made directly by the target frame or transitively by a nested callee. Exclude calls before or after that interval, calls to every function not in the listed set, builtins, and synthetic comprehension or generator-expression frames. Retain every repeated call. If a listed function were a generator, each resume that produces a Python `call` trace event would be retained as another call; none of the listed functions is a generator.

Function identities use the fully qualified dotted format `module.Class.method` or `module.function`; for example, `pkg.tools.Widget.run`. For every answer element, `file` is the repo-relative POSIX path of the called function's code and `func` is its function identity in that format.

Return exactly one JSON object with the shape `{"function_call_order": [{"file": "str", "func": "str"}]}`. Each list element represents one included call event. Preserve total chronological event order, with original event occurrence order as the tie-breaker; do not sort and do not deduplicate. Encode both fields as JSON strings. No answer value uses `repr`, `str`, line numbers, exception-name formatting, an empty-value sentinel, or JSON null; `file` and `func` are the strings defined above."""


def parse_call_order(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    invocation_number = 0
    selected_active = False
    target_events = 0
    call_order: list[dict[str, str]] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match:
            continue
        file_path = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")

        if func == TARGET_FUNC and file_path.endswith(TARGET_FILE):
            target_events += 1
            if event == "call":
                invocation_number += 1
                selected_active = invocation_number == INVOCATION
                if selected_active:
                    call_order.append({"file": TARGET_FILE, "func": TARGET_FUNC})
                continue
            if event == "return" and selected_active:
                selected_active = False
                continue

        if (
            selected_active
            and event == "call"
            and func in TRACKED_SET
            and file_path.endswith(TARGET_FILE)
        ):
            call_order.append({"file": TARGET_FILE, "func": func})

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations; "
            f"cannot select invocation {INVOCATION}"
        )
    if selected_active:
        raise RuntimeError(f"invocation {INVOCATION} has no matching return event")
    if not call_order:
        raise RuntimeError(f"invocation {INVOCATION} contains zero tracked calls")
    return call_order


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True, type=Path)
    arg_parser.add_argument("--out", required=True, type=Path)
    args = arg_parser.parse_args()

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {
            "function_call_order": parse_call_order(args.trace_log)
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
