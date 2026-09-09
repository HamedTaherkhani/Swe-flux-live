import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/sansio/blueprints.py"
TARGET_FUNC = "flask.sansio.blueprints.Blueprint._merge_blueprint_funcs"
TRACKED_FUNCS = {
    TARGET_FUNC,
    f"{TARGET_FUNC}.<locals>.<dictcomp>",
    f"{TARGET_FUNC}.<locals>.extend",
}
TRACE_LINE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>\w+)\b"
)

QUESTION = """Run the pytest test
`flask_qa/blueprints_merge_blueprint_funcs_s6_calls/files/testcase.py::TestBlueprintMergeRuntime::test_repeated_registration_call_path`
against this repository. During that test, consider the third invocation of
`flask.sansio.blueprints.Blueprint._merge_blueprint_funcs` in
`src/flask/sansio/blueprints.py`. An invocation is one Python `call` event for
that exact function, and invocations are numbered from 1 in chronological
event order.

Report the ordered cross-function executed-line path while that third
invocation is on the call stack. Include `line` events from exactly these
runtime functions:

* `flask.sansio.blueprints.Blueprint._merge_blueprint_funcs`
* `flask.sansio.blueprints.Blueprint._merge_blueprint_funcs.<locals>.<dictcomp>`
* `flask.sansio.blueprints.Blueprint._merge_blueprint_funcs.<locals>.extend`

Thus, include events in the target frame itself and in any invocation of either
listed nested function that occurs before the target invocation returns,
whether reached directly or transitively. Exclude every function not in that
set, including builtins and other comprehension frames, and exclude `call`,
`return`, and `exception` events. Keep every repeated line event; do not
deduplicate or sort. Order entries by the interpreter's chronological event
production order, which is already a total order, so no tie-breaker is needed.
None of the listed functions is a generator; no generator resumption is to be
treated as an additional target invocation.

Return exactly
`{"executed_path": [{"file": <string>, "func": <string>, "line": <integer>}, ...]}`.
For every entry, `file` is the repository-relative POSIX path
`src/flask/sansio/blueprints.py`; `func` is the full runtime dotted module and
qualified name (for example, `flask.sansio.app.App.register_blueprint`, not a
bare method name); and `line` is the absolute 1-based source line number in
that repository file. Under Python line-tracing semantics, a multi-line
statement or expression contributes the line on which its currently executed
source component begins. A function's `def` line, decorator lines, and
unexecuted docstring lines are not added unless Python actually emits a `line`
event for them. All three fields are JSON values, not Python `repr` strings;
there are no null or omitted fields."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_calls = 0
    active = False
    path: list[dict[str, object]] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_LINE.match(raw_line)
        if match is None:
            continue

        func = match.group("func")
        event = match.group("event")

        if func == TARGET_FUNC and event == "call":
            target_calls += 1
            if target_calls == 3:
                active = True

        if active and event == "line" and func in TRACKED_FUNCS:
            source_path = match.group("file").replace("\\", "/")
            if not source_path.endswith(f"/{TARGET_FILE}"):
                fail(f"unexpected source file for tracked event: {source_path}")
            path.append(
                {
                    "file": TARGET_FILE,
                    "func": func,
                    "line": int(match.group("line")),
                }
            )

        if active and func == TARGET_FUNC and event == "return":
            active = False
            break

    if target_calls == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls < 3:
        fail(f"trace contains only {target_calls} target invocation(s), need 3")
    if active:
        fail("third target invocation has no return event")
    if not path:
        fail("third target invocation produced no tracked line events")

    observed_funcs = {entry["func"] for entry in path}
    missing_funcs = TRACKED_FUNCS - observed_funcs
    if missing_funcs:
        fail(f"tracked functions produced no line events: {sorted(missing_funcs)}")

    return path


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    executed_path = parse_trace(args.trace_log)
    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out} with {len(executed_path)} executed-path entries")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
