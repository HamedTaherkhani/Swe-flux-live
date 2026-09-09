#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/api/chat.py"
TARGET_FUNC_SUFFIXES = (".src.llamafactory.api.chat._process_request", "._process_request")

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"\bexc=(?P<exc_type>[A-Za-z_][A-Za-z0-9_]*)\:\s(?P<exc_repr>.+?)\s+locals=")

TYPE_FQN = {
    "JSONDecodeError": "json.decoder.JSONDecodeError",
    "RuntimeError": "builtins.RuntimeError",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def read_trace_lines(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"Trace log not found: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def normalize_message(exc_repr: str) -> str:
    match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*\((?P<inner>.*)\)$", exc_repr)
    if match:
        inner = match.group("inner")
        try:
            return str(ast.literal_eval(inner))
        except (ValueError, SyntaxError):
            pass
    return exc_repr


def parse_target_invocations(trace_lines: list[str]) -> list[list[dict[str, object]]]:
    matched_events = 0
    call_stack: list[list[dict[str, object]]] = []
    invocations: list[list[dict[str, object]]] = []

    for raw_line in trace_lines:
        match = TRACE_RE.match(raw_line)
        if match is None:
            continue

        file_path = match.group("file").replace("\\", "/")
        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue

        func_name = match.group("func")
        if not any(func_name.endswith(suffix) for suffix in TARGET_FUNC_SUFFIXES):
            continue

        matched_events += 1
        event = match.group("event")
        lineno = int(match.group("lineno"))
        rest = match.group("rest")

        if event == "call":
            call_stack.append([])
            continue

        if not call_stack:
            raise SystemExit(f"Malformed trace: {event} without active _process_request call. Line: {raw_line}")

        event_record: dict[str, object] = {"event": event, "line": lineno}

        if event == "exception":
            exc_match = EXC_RE.search(rest)
            if exc_match is None:
                raise SystemExit(f"Malformed exception trace line for _process_request: {raw_line}")
            exc_type = exc_match.group("exc_type")
            exc_repr = exc_match.group("exc_repr")
            event_record["exception_type"] = TYPE_FQN.get(exc_type, exc_type)
            event_record["message"] = normalize_message(exc_repr)

        call_stack[-1].append(event_record)

        if event == "return":
            invocations.append(call_stack.pop())

    if matched_events == 0:
        raise SystemExit("Trace contains zero events for target function _process_request.")
    if call_stack:
        for pending in call_stack:
            if not pending:
                raise SystemExit("Malformed trace: empty unterminated _process_request invocation.")
            if pending[-1]["event"] != "exception":
                raise SystemExit("Malformed trace: unterminated _process_request invocation without terminal exception.")
            invocations.append(pending)
    if not invocations:
        raise SystemExit("Trace contained target events but no completed invocations.")
    return invocations


def compute_exception_events(invocations: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    exception_events: list[dict[str, object]] = []
    for invocation in invocations:
        for idx, event in enumerate(invocation):
            if event["event"] != "exception":
                continue
            handled = any(next_event["event"] == "line" for next_event in invocation[idx + 1 :])
            exception_events.append(
                {
                    "line": int(event["line"]),
                    "exception_type": str(event["exception_type"]),
                    "message": str(event["message"]),
                    "handled": handled,
                }
            )

    if not exception_events:
        raise SystemExit("No exception events were observed in target function _process_request.")
    return exception_events


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    invocations = parse_target_invocations(trace_lines)
    exception_events = compute_exception_events(invocations)

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/chat_process_request_s5_exceptions/files/testcase.py::"
            "TestChatProcessRequestS5Exceptions::test_jsondecodeerror_then_runtimeerror_propagates`, "
            "consider function `src.llamafactory.api.chat._process_request` in "
            "`src/llamafactory/api/chat.py`. "
            "An `exception event` means any runtime point in this function where an exception is reported at a source "
            "line while the call is active. For each such event, record: `line` (int source line number in this file), "
            "`exception_type` (str fully qualified exception type name), `message` (str equal to `str(exc)`), and "
            "`handled` (bool, true iff execution continues to at least one later `line` event in the same invocation of "
            "this function; false iff no later line event occurs in that invocation, i.e., the exception propagates out). "
            "Return JSON with exactly one key `exception_events`, whose value is an array of objects with keys "
            "`line` (int), `exception_type` (str), `message` (str), and `handled` (bool). "
            "Order entries by their runtime occurrence order; do not reorder or deduplicate."
        ),
        "template_answer": {
            "exception_events": [{"line": "int", "exception_type": "str", "message": "str", "handled": "bool"}]
        },
        "oracle_answer": {"exception_events": exception_events},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], ensure_ascii=True))


if __name__ == "__main__":
    main()
