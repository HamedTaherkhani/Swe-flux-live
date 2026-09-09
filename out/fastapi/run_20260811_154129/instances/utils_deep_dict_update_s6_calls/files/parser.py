from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "fastapi/utils.py"
TARGET_FUNC = "fastapi.utils.deep_dict_update"
TRACKED_FILES = {
    TARGET_FUNC: TARGET_FILE,
    "testcase.ProbeDict.items": (
        "fastapi_qa/utils_deep_dict_update_s6_calls/files/testcase.py"
    ),
    "testcase.ProbeDict.__contains__": (
        "fastapi_qa/utils_deep_dict_update_s6_calls/files/testcase.py"
    ),
    "testcase.ProbeDict.__getitem__": (
        "fastapi_qa/utils_deep_dict_update_s6_calls/files/testcase.py"
    ),
    "testcase.ProbeDict.__setitem__": (
        "fastapi_qa/utils_deep_dict_update_s6_calls/files/testcase.py"
    ),
}

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/utils_deep_dict_update_s6_calls/files/testcase.py::DeepDictUpdateCallGraphTest::test_generated_recursive_mapping_merge`
against this repository. The primary target is
`fastapi.utils.deep_dict_update` in `fastapi/utils.py`.

Report the ordered Python call-event sequence for the first invocation of the
primary target, considering exactly this tracked function set:

- `fastapi.utils.deep_dict_update`
- `testcase.ProbeDict.items`
- `testcase.ProbeDict.__contains__`
- `testcase.ProbeDict.__getitem__`
- `testcase.ProbeDict.__setitem__`

An invocation means one Python `call` event for a function. Target invocations
are numbered 1-based in chronological call-event order, including recursive
invocations, so invocation 1 is the outermost call made directly by the named
test. Start the sequence with the `call` event that creates target invocation
1. Then include every later `call` event for a member of the tracked set while
that invocation's frame remains on the Python call stack, through all direct,
nested, transitive, and recursive calls. Stop when that outer frame returns.
Exclude calls before it starts and after it returns. Exclude every function
outside the tracked set, including builtins and comprehension frames.

Preserve every included event in chronological call-event order. Do not sort
or deduplicate: repeated and recursive calls produce repeated entries. If a
tracked generator were resumed and Python emitted another `call` event for its
frame, that resumption would produce another entry under the same rule.
Return exactly
`{"function_call_order": [{"file": <string>, "func": <string>}, ...]}`.

For each entry, `file` is the repository-relative POSIX path of the defining
source file and `func` is the full dotted Python `module.qualname`; for
example, `package.module.Widget.run` in `package/module.py`. Do not use a bare
name or remove the module prefix. The list has no secondary sorting or
tie-breaker because Python call events form the total chronological order;
events emitted earlier appear earlier. The result uses normal JSON object and
string serialization. There are no line numbers, stringified Python values,
null placeholders, omitted entries, or empty-value sentinels."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def repo_relative(absolute_file: str, root: Path) -> str:
    try:
        return Path(absolute_file).resolve().relative_to(root).as_posix()
    except ValueError:
        fail(f"traced file is outside repository root {root}: {absolute_file}")


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = [
        (
            match.group("file"),
            int(match.group("line")),
            match.group("func"),
            match.group("event"),
        )
        for match in EVENT_RE.finditer(trace_text)
    ]
    if not events:
        fail("trace log contains no parseable function events")

    target_events = [event for event in events if event[2] == TARGET_FUNC]
    if not target_events:
        fail(f"trace log contains zero events for target function {TARGET_FUNC}")

    target_files = {
        Path(file_name).resolve()
        for file_name, _line, func, _event in target_events
        if func == TARGET_FUNC
    }
    if len(target_files) != 1:
        fail(f"target events came from {len(target_files)} distinct files")
    target_path = next(iter(target_files))
    if not target_path.as_posix().endswith(f"/{TARGET_FILE}"):
        fail(f"target event came from unexpected file: {target_path}")
    root = target_path
    for _part in Path(TARGET_FILE).parts:
        root = root.parent

    call_order: list[dict[str, str]] = []
    capturing = False
    completed = False
    target_depth = 0

    for absolute_file, _line, func, event in events:
        if func == TARGET_FUNC and event == "call":
            if not capturing and not completed:
                capturing = True
                target_depth = 1
            elif capturing:
                target_depth += 1

        if capturing and event == "call" and func in TRACKED_FILES:
            relative_file = repo_relative(absolute_file, root)
            expected_file = TRACKED_FILES[func]
            if relative_file != expected_file:
                fail(
                    f"tracked function {func} came from {relative_file}, "
                    f"expected {expected_file}"
                )
            call_order.append({"file": relative_file, "func": func})

        if capturing and func == TARGET_FUNC and event == "return":
            target_depth -= 1
            if target_depth < 0:
                fail("target return events made call depth negative")
            if target_depth == 0:
                capturing = False
                completed = True
                break

    if not completed:
        fail("first target invocation did not have a matching return event")
    if not call_order:
        fail("first target invocation produced an empty tracked call sequence")
    if call_order[0] != {"file": TARGET_FILE, "func": TARGET_FUNC}:
        fail("tracked call sequence does not start with the first target call")

    target_line_events = [
        line for _file, line, func, event in target_events if event == "line"
    ]
    called_functions = {entry["func"] for entry in call_order}
    if len(target_line_events) < 40:
        fail(f"target trace has only {len(target_line_events)} line events")
    if len(set(target_line_events)) < 8:
        fail(
            f"target trace has only {len(set(target_line_events))} distinct lines"
        )
    if len(call_order) < 10:
        fail(f"tracked sequence has only {len(call_order)} call events")
    if len(called_functions) < 2:
        fail(f"tracked sequence has only {len(called_functions)} functions")

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {len(call_order)} calls across {len(called_functions)} "
        f"tracked functions to {out_path}"
    )


if __name__ == "__main__":
    main()
