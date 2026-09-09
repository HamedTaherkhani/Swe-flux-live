import argparse
import json
from pathlib import Path
import re
import sys


INSTANCE_TEST = (
    "flask_qa/provider_response_s6_calls/files/testcase.py::"
    "TestProviderResponseCalls::test_seeded_response_matrix"
)
TARGET_FILE = "src/flask/json/provider.py"
TARGET_FUNC = "flask.json.provider.DefaultJSONProvider.response"
INVOCATION = 13
TRACKED_FUNCTIONS = (
    "flask.json.provider.DefaultJSONProvider.response",
    "flask.json.provider.JSONProvider._prepare_response_obj",
    "flask.json.provider.DefaultJSONProvider.dumps",
    "flask.json.provider._default",
)

QUESTION = f"""Run the pytest test `{INSTANCE_TEST}` against this repository. What is
the exact cross-function executed line path during the {INVOCATION}th invocation
of `{TARGET_FUNC}` in `{TARGET_FILE}`?

An invocation is one Python `call` event for exactly `{TARGET_FUNC}`, counted
1-based in chronological order over the entire test run. The selected
invocation is active from that call event through its matching `return` event,
inclusive. Track exactly these functions, and no others:
- `flask.json.provider.DefaultJSONProvider.response`
- `flask.json.provider.JSONProvider._prepare_response_obj`
- `flask.json.provider.DefaultJSONProvider.dumps`
- `flask.json.provider._default`

Include every Python `line` event in any tracked function whenever it occurs
while the selected target invocation is active. This includes events in the
target's own frame and in listed functions called either directly or
transitively while that target frame is on the stack. Exclude all `call`,
`return`, and `exception` events themselves; all events in functions outside
the tracked set; and calls to listed functions made when the selected target
invocation is not active. Repeated calls and repeated line events are preserved
as separate entries. If a generator resumption produces another `call` event,
that event is not itself output, but every resulting qualifying `line` event
is included.

Report entries in chronological occurrence order, first observed event first.
Do not sort or deduplicate them; chronological occurrence is the complete
ordering rule and needs no tie-breaker. `line` is the standard Python tracing
event's `frame.f_lineno`: a 1-based physical line number in `{TARGET_FILE}` as
it exists in the repository. For a multi-line statement or expression, each
event uses the physical line where the interpreter reports that statement or
subexpression beginning; do not normalize continuation lines to an enclosing
statement's first line. The function `def` line is associated with the ignored
`call` event, docstring-only lines do not execute, and decorator evaluation
occurs outside the selected invocation, so none is included unless Python
actually emits a qualifying `line` event there.

Return exactly one JSON object with shape
`{{"executed_path": [{{"file": "str", "func": "str", "line": "int"}}]}}`.
For each entry, `file` is the repo-relative POSIX path `{TARGET_FILE}`. `func`
is the full runtime dotted `module.qualname` of the frame, such as
`example.widgets.Gadget.render` (never a bare function or method name), and
`line` is the integer defined above. Strings are ordinary JSON strings; no
`repr()` or `str()` formatting of runtime values is involved. Every qualifying
event has all three fields, so there is no null, empty, or omitted-value
representation. Do not emit any additional keys."""


def parse_trace(trace_path: Path) -> dict:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"(?P<file>\S*src/flask/json/provider\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    tracked = set(TRACKED_FUNCTIONS)
    target_events = 0
    invocation_count = 0
    selected_active = False
    selected_complete = False
    selected_path = []
    seen_tracked_calls = set()

    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(raw)
        if match is None:
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_events += 1

        if event == "call" and func in tracked:
            seen_tracked_calls.add(func)

        if event == "call" and func == TARGET_FUNC:
            invocation_count += 1
            if invocation_count == INVOCATION:
                if selected_active or selected_complete:
                    raise RuntimeError("selected target invocation overlaps itself")
                selected_active = True

        if selected_active and event == "line" and func in tracked:
            selected_path.append(
                {
                    "file": TARGET_FILE,
                    "func": func,
                    "line": int(match.group("line")),
                }
            )

        if selected_active and event == "return" and func == TARGET_FUNC:
            selected_active = False
            selected_complete = True

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )
    if invocation_count < INVOCATION:
        raise RuntimeError(
            f"trace has only {invocation_count} target invocations; "
            f"need invocation {INVOCATION}"
        )
    if selected_active or not selected_complete:
        raise RuntimeError("trace ended before the selected invocation completed")
    if not selected_path:
        raise RuntimeError("selected invocation contains zero qualifying line events")
    if len(seen_tracked_calls) < 2:
        raise RuntimeError("trace contains call events for fewer than two tracked functions")

    return {"executed_path": selected_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    answer = parse_trace(args.trace_log)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote oracle to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
