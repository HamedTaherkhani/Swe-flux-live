#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/hparams/parser.py"
TARGET_FUNC = "llamafactory.hparams.parser.get_infer_args"
TRACKED_FUNCS = {
    "llamafactory.hparams.parser._check_extra_dependencies",
    "llamafactory.hparams.parser._parse_args",
    "llamafactory.hparams.parser._parse_infer_args",
    "llamafactory.hparams.parser._set_transformers_logging",
    "llamafactory.hparams.parser._verify_model_args",
    "llamafactory.hparams.parser.get_eval_args",
    "llamafactory.hparams.parser.get_infer_args",
    "llamafactory.hparams.parser.get_train_args",
    "llamafactory.hparams.parser.read_args",
}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/parser_get_infer_args_m6_calls/files/testcase.py::"
    "TestIndirectInferArgumentCallGraph::test_seeded_chat_model_construction_matrix`. The primary "
    "target is `llamafactory.hparams.parser.get_infer_args` in "
    "`src/llamafactory/hparams/parser.py`. Report `covered_functions` for exactly this tracked set, "
    "all defined in that file: `llamafactory.hparams.parser._check_extra_dependencies`, "
    "`llamafactory.hparams.parser._parse_args`, "
    "`llamafactory.hparams.parser._parse_infer_args`, "
    "`llamafactory.hparams.parser._set_transformers_logging`, "
    "`llamafactory.hparams.parser._verify_model_args`, "
    "`llamafactory.hparams.parser.get_eval_args`, "
    "`llamafactory.hparams.parser.get_infer_args`, "
    "`llamafactory.hparams.parser.get_train_args`, and "
    "`llamafactory.hparams.parser.read_args`. A tracked function is covered exactly when execution "
    "of the test method causes Python to emit at least one `call` event for a frame whose exact "
    "runtime function identity is that tracked identity. Consider call events anywhere in the "
    "complete test-method execution: a call may be made directly by a listed function, transitively "
    "while one is on the stack, or from another frame before or after the primary target's frame. "
    "Calls to functions outside the listed set do not count. An invocation means one Python `call` "
    "event for that function; invocations are 1-based in chronological call-event order if they "
    "must be reasoned about, but invocation numbers and call counts are not emitted. Repeated and "
    "recursive calls are deduplicated, so each covered identity produces exactly one output object. "
    "For generators and coroutines, count a resumption only if Python emits a `call` event for the "
    "exact tracked identity, and deduplicate repeated resumptions in the same way. Function identity "
    "is the full runtime dotted `module.qualname` (for example, `pkg.worker.Engine.run`; a module "
    "function would be `pkg.worker.execute`). Emit covered members only, with no placeholder for an "
    "uncovered member. Sort the deduplicated objects in ascending lexicographic order by the "
    "two-key tuple (`file`, `func`), comparing complete JSON string values by Unicode code-point "
    "order; that tuple is the full tie-break rule. In each object, `file` is the POSIX "
    "repo-relative source path without a leading `./` (for example, `pkg/worker.py`), and `func` is "
    "the dotted identity just defined. Return exactly one JSON object with the single key "
    "`covered_functions`; its value is a JSON array, and every array element has exactly the two "
    "JSON string fields `file` and `func`. There is no chronological ordering after set "
    "deduplication. No `repr` or `str` conversion of runtime values, exception-name convention, "
    "null convention, or line-number convention applies, because every answer leaf is a source-path "
    "or function-identity JSON string."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/hparams/parser\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_cli():
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
        if match and match.group("func") in TRACKED_FUNCS:
            events.append((match.group("func"), match.group("event")))
    return events


def compute_covered(events):
    target_events = [event for func, event in events if func == TARGET_FUNC]
    if not target_events:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if "call" not in target_events:
        fail(f"trace contains zero call events for target function {TARGET_FUNC}")

    called = {func for func, event in events if event == "call"}
    if not called:
        fail("computed covered function set is empty")
    return sorted(
        ({"file": TARGET_FILE, "func": func} for func in called),
        key=lambda item: (item["file"], item["func"]),
    )


def main():
    args = parse_cli()
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
