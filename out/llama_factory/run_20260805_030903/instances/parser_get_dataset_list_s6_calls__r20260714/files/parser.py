import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "src.llamafactory.data.parser.get_dataset_list"
INVOCATION_INDEX = 3

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def load_events(trace_path: Path) -> list[tuple[str, str]]:
    if not trace_path.exists():
        raise RuntimeError(f"Trace log not found: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"Trace log is empty: {trace_path}")

    events: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        match = LINE_RE.match(raw_line)
        if not match:
            continue
        func = match.group("func")
        event = match.group("event")
        events.append((func, event))

    if not events:
        raise RuntimeError("No parseable trace events were found in trace log.")

    return events


def compute_callee_sequence(events: list[tuple[str, str]]) -> list[str]:
    stack: list[str] = []
    invocation_count = 0
    seq_by_invocation: dict[int, list[str]] = {}

    for func, event in events:
        if event == "call":
            caller = stack[-1] if stack else None
            stack.append(func)

            if func == TARGET_FUNC:
                invocation_count += 1
                seq_by_invocation[invocation_count] = []
            elif caller == TARGET_FUNC and invocation_count >= 1:
                seq_by_invocation.setdefault(invocation_count, []).append(func)

        elif event in {"return", "exception"}:
            if stack and stack[-1] == func:
                stack.pop()
            elif func in stack:
                # Defensive recovery for any unmatched tracing edge cases.
                idx = len(stack) - 1 - stack[::-1].index(func)
                del stack[idx:]

    if invocation_count == 0:
        raise RuntimeError(f"Trace contains zero events for target function: {TARGET_FUNC}")

    if invocation_count < INVOCATION_INDEX:
        raise RuntimeError(
            f"Expected at least {INVOCATION_INDEX} invocations of {TARGET_FUNC}, got {invocation_count}."
        )

    callee_sequence = seq_by_invocation.get(INVOCATION_INDEX, [])
    if not callee_sequence:
        raise RuntimeError(
            f"Invocation {INVOCATION_INDEX} of {TARGET_FUNC} had no captured direct callees."
        )

    return callee_sequence


def build_oracle(callee_sequence: list[str]) -> dict:
    question = (
        "In the test `llama_factory_qa/parser_get_dataset_list_s6_calls__r20260714/files/testcase.py` "
        "for `TestParserGetDatasetListS6Calls.test_dynamic_callee_sequence_third_invocation`, "
        "consider the 3rd runtime invocation of "
        "`src.llamafactory.data.parser.get_dataset_list` in "
        "`src/llamafactory/data/parser.py`.\n\n"
        "Function identity must be reported as dotted qualified names in the format "
        "`module.Class.method` or `module.function`.\n"
        "Define call ordering strictly by dynamic `call` events.\n"
        "For this 3rd invocation, compute the exact ordered list of direct callees of "
        "`src.llamafactory.data.parser.get_dataset_list` restricted to callees whose qualified names are exactly one of:\n"
        "- `src.llamafactory.extras.misc.use_modelscope`\n"
        "- `src.llamafactory.extras.misc.use_openmind`\n"
        "- `src.llamafactory.data.parser.join`\n\n"
        "Output JSON must contain exactly one key:\n"
        "- `callee_sequence` (type: array of strings), preserving execution order with no sorting."
    )

    return {
        "question_kind": "S6_InterProceduralCFG",
        "question": question,
        "template_answer": {"callee_sequence": ["str"]},
        "oracle_answer": {"callee_sequence": callee_sequence},
    }


def main() -> None:
    args = parse_args()
    events = load_events(Path(args.trace_log))
    callee_sequence = compute_callee_sequence(events)
    oracle = build_oracle(callee_sequence)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"[parser_get_dataset_list_s6_calls__r20260714] {exc}", file=sys.stderr)
        raise
