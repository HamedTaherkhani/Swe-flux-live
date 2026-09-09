import argparse
import json
from pathlib import Path
import re
import sys


INSTANCE_TEST = (
    "flask_qa/ctx_push_m6_calls/files/testcase.py::"
    "TestContextPushGraph::test_seeded_context_matrix"
)
TARGET_FILE = "src/flask/ctx.py"
TARGET_FUNC = "flask.ctx.AppContext.push"
TRACKED_FUNCTIONS = (
    "flask.ctx.AppContext.push",
    "flask.ctx.AppContext._get_session",
    "flask.ctx.AppContext.request",
    "flask.ctx.AppContext.match_request",
    "flask.ctx.AppContext.session",
    "flask.ctx.AppContext.copy",
)

QUESTION = f"""Run the pytest test `{INSTANCE_TEST}` against this repository. During
that test, which members of the tracked function set below execute at least
once while an invocation of `{TARGET_FUNC}` in `{TARGET_FILE}` is active?

Tracked function set (and no other functions):
- `flask.ctx.AppContext.push`
- `flask.ctx.AppContext._get_session`
- `flask.ctx.AppContext.request`
- `flask.ctx.AppContext.match_request`
- `flask.ctx.AppContext.session`
- `flask.ctx.AppContext.copy`

A function executes when Python begins one invocation of exactly that function
(a Python `call` event for its frame). A `{TARGET_FUNC}` invocation is active
from its `call` event through its matching `return` event, inclusive. Thus,
include the outer `push` invocation itself and any listed function whose call
begins anywhere while a `push` frame is on the stack, whether called directly
by `push` or transitively by a nested callee. Ignore listed-function calls made
when no `push` frame is active, and ignore all functions outside the tracked
set. An invocation is one `call` event, counted 1-based in chronological order
over the entire test run. Recursive or overlapping `push` invocations use the
same stack rule. Repeated calls, recursion, and generator resumptions that
produce further `call` events establish coverage but do not create duplicate
output entries.

Return exactly one JSON object with shape
`{{"covered_functions": [{{"file": "str", "func": "str"}}]}}`. Emit one object
per covered tracked function, deduplicated across the complete test run.
For every object, `file` is the repo-relative POSIX path containing the
function and `func` is the full runtime dotted `module.qualname` (for example,
`package.Widget.run`, never a bare method name). Sort the objects ascending
first by `file`, then by `func`, comparing the Unicode code points of the
complete strings; this is the total ordering rule, so no further tie-breaker
is needed. Strings are ordinary JSON strings, and no `repr()` or `str()`
conversion of runtime values is involved. Do not emit uncovered functions or
any additional keys."""


def parse_trace(trace_path: Path) -> dict:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"(?P<file>\S*src/flask/ctx\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    tracked = set(TRACKED_FUNCTIONS)
    covered = set()
    active_pushes = 0
    target_events = 0

    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(raw)
        if match is None:
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_events += 1

        if event == "call":
            if func == TARGET_FUNC:
                active_pushes += 1
            if active_pushes > 0 and func in tracked:
                covered.add(func)
        elif event == "return" and func == TARGET_FUNC:
            if active_pushes == 0:
                raise RuntimeError("target return event has no active target invocation")
            active_pushes -= 1

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )
    if active_pushes != 0:
        raise RuntimeError(
            f"trace ended with {active_pushes} active target invocation(s)"
        )
    if TARGET_FUNC not in covered:
        raise RuntimeError("target function had events but no qualifying call event")

    answer_items = sorted(
        ({"file": TARGET_FILE, "func": func} for func in covered),
        key=lambda item: (item["file"], item["func"]),
    )
    return {"covered_functions": answer_items}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    answer = parse_trace(args.trace_log)
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
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
