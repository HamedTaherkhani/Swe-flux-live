import argparse
import json
import os
import re
import sys


TARGET_FILE_SUFFIX = "/src/llamafactory/chat/vllm_engine.py"
TARGET_FUNC_SUFFIXES = ("VllmEngine._generate", "_generate")

TRACKED_VARIABLES = ["max_tokens", "multi_modal_data"]
DEF_LINES = {
    "max_tokens": {146, 149, 151, 154, 157},
    "multi_modal_data": {177, 185, 199, 201},
}
USE_LINES = {
    "max_tokens": {170},
    "multi_modal_data": {204},
}

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def load_trace_lines(trace_path):
    if not os.path.exists(trace_path):
        raise FileNotFoundError(f"Trace log not found: {trace_path}")
    with open(trace_path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f]
    if not lines:
        raise RuntimeError(f"Trace log is empty: {trace_path}")
    return lines


def extract_target_events(lines):
    events = []
    for raw in lines:
        m = TRACE_RE.match(raw)
        if not m:
            continue
        file_path = m.group("file").replace("\\", "/")
        lineno = int(m.group("lineno"))
        funcname = m.group("func")
        event = m.group("event")
        if file_path.endswith(TARGET_FILE_SUFFIX) and any(funcname.endswith(suffix) for suffix in TARGET_FUNC_SUFFIXES):
            events.append({"lineno": lineno, "event": event})
    return events


def compute_answer(events):
    invocation_index = 0
    active = None
    observed_pairs = []
    dead_defs = []

    target_event_count = len(events)
    if target_event_count == 0:
        raise RuntimeError("No target function events found in trace log.")

    for event in events:
        event_type = event["event"]
        lineno = event["lineno"]

        if event_type == "call":
            invocation_index += 1
            active = {
                "invocation_index": invocation_index,
                "definitions": {var: [] for var in TRACKED_VARIABLES},
                "current_def": {var: None for var in TRACKED_VARIABLES},
            }
            continue

        if active is None:
            continue

        if event_type == "line":
            for var in TRACKED_VARIABLES:
                if lineno in DEF_LINES[var]:
                    definition = {"def_line": lineno, "used": False}
                    active["definitions"][var].append(definition)
                    active["current_def"][var] = definition

            for var in TRACKED_VARIABLES:
                if lineno in USE_LINES[var]:
                    current_def = active["current_def"][var]
                    if current_def is not None:
                        current_def["used"] = True
                        observed_pairs.append(
                            {
                                "invocation_index": active["invocation_index"],
                                "variable": var,
                                "def_line": current_def["def_line"],
                                "use_line": lineno,
                            }
                        )

        if event_type in {"return", "exception"}:
            for var in TRACKED_VARIABLES:
                for definition in active["definitions"][var]:
                    if not definition["used"]:
                        dead_defs.append(
                            {
                                "invocation_index": active["invocation_index"],
                                "variable": var,
                                "def_line": definition["def_line"],
                            }
                        )
            active = None

    if invocation_index == 0:
        raise RuntimeError("Target function never entered; no call events observed.")

    observed_pairs = sorted(
        observed_pairs,
        key=lambda x: (x["invocation_index"], x["variable"], x["def_line"], x["use_line"]),
    )
    dead_defs = sorted(
        dead_defs,
        key=lambda x: (x["invocation_index"], x["variable"], x["def_line"]),
    )

    return {
        "tracked_variables": sorted(TRACKED_VARIABLES),
        "observed_def_use_pairs": observed_pairs,
        "dead_defs": dead_defs,
    }


def build_question():
    return (
        "For the pytest test `llama_factory_qa/vllm_engine_generate_m4_dataflow__r20260714/files/testcase.py::"
        "TestVllmEngineGenerateM4DataFlow::test_branch_sensitive_dataflow`, analyze runtime data flow in "
        "`src.llamafactory.chat.vllm_engine.VllmEngine._generate` "
        "(file `src/llamafactory/chat/vllm_engine.py`). "
        "Track exactly these variables: `max_tokens` and `multi_modal_data`. "
        "A dynamic definition is counted whenever an executed line in this function is one of the assignment lines "
        "{146,149,151,154,157} for `max_tokens` or {177,185,199,201} for `multi_modal_data`. "
        "A dynamic use is counted whenever an executed line in this function is line 170 for `max_tokens` or "
        "line 204 for `multi_modal_data`. "
        "Invocation indices start at 1 and increase on each call to `_generate` during this test method only. "
        "For each invocation, pair each use with the most recent prior definition of the same variable in that "
        "invocation. "
        "If a definition is followed by another definition of the same variable before any counted use, or the "
        "invocation returns before any counted use, that earlier definition is a dead definition. "
        "Return JSON with keys: `tracked_variables` (list[str]), `observed_def_use_pairs` "
        "(list[object with `invocation_index` int, `variable` str, `def_line` int, `use_line` int]), and "
        "`dead_defs` (list[object with `invocation_index` int, `variable` str, `def_line` int]). "
        "Sort `tracked_variables` lexicographically; sort `observed_def_use_pairs` by "
        "(`invocation_index`, `variable`, `def_line`, `use_line`); sort `dead_defs` by "
        "(`invocation_index`, `variable`, `def_line`)."
    )


def main():
    args = parse_args()
    lines = load_trace_lines(args.trace_log)
    events = extract_target_events(lines)
    answer = compute_answer(events)

    payload = {
        "question_kind": "M4_DataFlow",
        "question": build_question(),
        "template_answer": {
            "tracked_variables": ["str"],
            "observed_def_use_pairs": [
                {
                    "invocation_index": "int",
                    "variable": "str",
                    "def_line": "int",
                    "use_line": "int",
                }
            ],
            "dead_defs": [{"invocation_index": "int", "variable": "str", "def_line": "int"}],
        },
        "oracle_answer": answer,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, sort_keys=True, indent=2)
        f.write("\n")

    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[parser-error] {exc}", file=sys.stderr)
        raise
