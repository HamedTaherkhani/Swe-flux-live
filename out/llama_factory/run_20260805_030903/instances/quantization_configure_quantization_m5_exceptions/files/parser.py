import argparse
import json
import re
import sys
from pathlib import Path


TRACE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.*?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?: (?P<data>.*))?$"
)

EXC_RE = re.compile(r"exc=(?P<type>[A-Za-z_][\w.]*)\s*:\s*(?P<value>.*?)(?:\s+locals=|$)")
VALUE_CALL_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\((?P<inner>.*)\)$")


def _die(msg: str) -> None:
    raise SystemExit(msg)


def _parse_exception_identity(exc_data: str) -> tuple[str, str]:
    match = EXC_RE.search(exc_data)
    if not match:
        return "unknown.UnknownException", exc_data.strip()

    raw_type = match.group("type").strip()
    raw_value = match.group("value").strip()
    value_match = VALUE_CALL_RE.match(raw_value)
    message = raw_value

    if value_match:
        inner = value_match.group("inner")
        if inner.startswith("'") and inner.endswith("'"):
            message = inner[1:-1]
        elif inner.startswith('"') and inner.endswith('"'):
            message = inner[1:-1]
        elif inner == "":
            message = ""

    if "." not in raw_type:
        qualified_type = f"builtins.{raw_type}"
    else:
        qualified_type = raw_type

    return qualified_type, message


def _build_question() -> str:
    return (
        "For the pytest test `llama_factory_qa/quantization_configure_quantization_m5_exceptions/files/testcase.py"
        "::TestConfigureQuantizationExceptions::test_raise_handle_matrix`, analyze runtime behavior of "
        "`src.llamafactory.model.model_utils.quantization.configure_quantization` in "
        "`src/llamafactory/model/model_utils/quantization.py`. "
        "Treat each runtime entry into that exact function as one invocation, ordered chronologically by execution; "
        "assign `invocation_index` starting at 1 in that order. "
        "Within each invocation, treat each exception raised from that function frame as one exception event, ordered "
        "chronologically within the invocation. "
        "For each invocation, output whether any exception is observed by the caller (`caller_saw_exception`: true iff "
        "the invocation has at least one exception event), and list its exception events as records containing: "
        "`line` (int source line where the exception event is emitted), `exception_type` (qualified type string), "
        "`exception_message` (exact message string), and `handled_where` (string, always `propagated` for this target "
        "if not handled inside the function). "
        "Return JSON with key `invocations` (list), sorted by `invocation_index`; each invocation's `exceptions` list "
        "must preserve chronological trace order, with ties broken by source line ascending."
    )


def parse_trace(trace_path: Path) -> dict:
    if not trace_path.exists():
        _die(f"Trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        _die(f"Trace log is empty: {trace_path}")

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    matched_events: list[dict] = []
    for raw in lines:
        match = TRACE_RE.match(raw)
        if not match:
            continue

        func = match.group("func")
        if not func.endswith(".configure_quantization"):
            continue

        matched_events.append(
            {
                "line": int(match.group("line")),
                "event": match.group("event"),
                "data": match.group("data") or "",
            }
        )

    if not matched_events:
        _die("Trace log has zero events for target function configure_quantization.")

    invocations: list[dict] = []
    current = None

    for evt in matched_events:
        if evt["event"] == "call":
            if current is not None:
                current["exceptions"].sort(key=lambda x: x["line"])
                current["caller_saw_exception"] = bool(current["exceptions"])
                invocations.append(current)
            current = {
                "invocation_index": len(invocations) + 1,
                "caller_saw_exception": False,
                "exceptions": [],
            }
            continue

        if current is None:
            continue

        if evt["event"] == "exception":
            exc_type, exc_message = _parse_exception_identity(evt["data"])
            current["exceptions"].append(
                {
                    "line": evt["line"],
                    "exception_type": exc_type,
                    "exception_message": exc_message,
                    "handled_where": "propagated",
                }
            )

        if evt["event"] == "return":
            current["exceptions"].sort(key=lambda x: x["line"])
            current["caller_saw_exception"] = bool(current["exceptions"])
            invocations.append(current)
            current = None

    if current is not None:
        current["exceptions"].sort(key=lambda x: x["line"])
        current["caller_saw_exception"] = bool(current["exceptions"])
        invocations.append(current)

    if not invocations:
        _die("Could not derive any function invocations from trace events.")

    return {"invocations": invocations}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    out_path = Path(args.out)

    oracle_answer = parse_trace(trace_path)
    payload = {
        "question_kind": "M5_Exceptions",
        "question": _build_question(),
        "template_answer": {
            "invocations": [
                {
                    "invocation_index": "int",
                    "caller_saw_exception": "bool",
                    "exceptions": [
                        {
                            "line": "int",
                            "exception_type": "str",
                            "exception_message": "str",
                            "handled_where": "str",
                        }
                    ],
                }
            ]
        },
        "oracle_answer": oracle_answer,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"Failed to build oracle: {exc}", file=sys.stderr)
        raise
