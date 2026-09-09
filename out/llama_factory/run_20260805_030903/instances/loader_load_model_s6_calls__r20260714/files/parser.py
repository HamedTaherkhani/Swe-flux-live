import argparse
import json
import re
import sys
from pathlib import Path


TRACE_PATTERN = re.compile(r" (?P<file>/.*?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)")
TARGET_FUNC = "src.llamafactory.model.loader.load_model"


def parse_trace(trace_path: Path) -> dict:
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace log not found: {trace_path}")

    content = trace_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Trace log is empty: {trace_path}")

    stack = []
    invocation_count = 0
    callers = set()
    matched_events = 0

    for raw_line in content.splitlines():
        match = TRACE_PATTERN.search(raw_line)
        if match is None:
            continue

        func = match.group("func")
        event = match.group("event")

        if event == "call":
            caller = stack[-1] if stack else None
            if func == TARGET_FUNC:
                invocation_count += 1
                matched_events += 1
                if caller is not None:
                    callers.add(caller)
            stack.append(func)
        elif event in {"return", "exception"}:
            if func == TARGET_FUNC:
                matched_events += 1
            if stack and stack[-1] == func:
                stack.pop()
            elif func in stack:
                stack.remove(func)

    if matched_events == 0 or invocation_count == 0:
        raise ValueError(f"No trace events captured for target function: {TARGET_FUNC}")

    return {
        "invocation_count": invocation_count,
        "callers": sorted(callers),
    }


def build_question() -> str:
    return (
        "During execution of the pytest test "
        "`llama_factory_qa/loader_load_model_s6_calls__r20260714/files/testcase.py::"
        "TestLoadModelS6Calls::test_invocation_callers`, consider calls to target function "
        "`src.llamafactory.model.loader.load_model` defined in file "
        "`src/llamafactory/model/loader.py`. Function identity is the dotted qualname format "
        "`module.Class.method` for methods or `module.function` for module-level functions. "
        "Count each invocation when a `call` event enters the target function body. Let `callers` "
        "be the set of immediate caller qualnames for those invocations, where the immediate caller "
        "is the qualname at the top of the active call stack just before each target `call` event. "
        "Return JSON with keys `invocation_count` (int) and `callers` (array of str). "
        "Sort `callers` in ascending lexicographic order with no duplicates."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    out_path = Path(args.out)

    oracle_answer = parse_trace(trace_path)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {"invocation_count": "int", "callers": ["str"]},
        "oracle_answer": oracle_answer,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[parser-error] {exc}", file=sys.stderr)
        raise
