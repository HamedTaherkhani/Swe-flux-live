from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/cli/starters.py"
TARGET_FUNC = (
    "kedro.framework.cli.starters._fetch_validate_parse_config_from_user_prompts"
)
TRACKED_FUNCS = {
    TARGET_FUNC,
    "kedro.framework.cli.starters._Prompt.__init__",
    "kedro.framework.cli.starters._Prompt.validate",
    "kedro.framework.cli.starters._parse_tools_input",
    "kedro.framework.cli.starters._parse_tools_input.<locals>._validate_range",
    "kedro.framework.cli.starters._validate_tool_selection",
    "kedro.framework.cli.starters._convert_tool_numbers_to_readable_names",
    "kedro.framework.cli.starters._parse_yes_no_to_bool",
}
RAW_TO_CANONICAL = {
    "kedro.framework.cli.starters.__init__": (
        "kedro.framework.cli.starters._Prompt.__init__"
    ),
    "kedro.framework.cli.starters.validate": (
        "kedro.framework.cli.starters._Prompt.validate"
    ),
    "kedro.framework.cli.starters._validate_range": (
        "kedro.framework.cli.starters._parse_tools_input.<locals>._validate_range"
    ),
}
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/starters_fetch_validate_parse_config_from_user_prompts_s6_calls/files/testcase.py::TestGeneratedInteractiveStarter::test_cli_generated_prompt_flow`
against this repository. For the first invocation of
`kedro.framework.cli.starters._fetch_validate_parse_config_from_user_prompts`
in `kedro/framework/cli/starters.py`, what is the exact ordered sequence of
tracked same-module function calls?

The tracked set is exactly these eight functions:

1. `kedro.framework.cli.starters._fetch_validate_parse_config_from_user_prompts`
2. `kedro.framework.cli.starters._Prompt.__init__`
3. `kedro.framework.cli.starters._Prompt.validate`
4. `kedro.framework.cli.starters._parse_tools_input`
5. `kedro.framework.cli.starters._parse_tools_input.<locals>._validate_range`
6. `kedro.framework.cli.starters._validate_tool_selection`
7. `kedro.framework.cli.starters._convert_tool_numbers_to_readable_names`
8. `kedro.framework.cli.starters._parse_yes_no_to_bool`

An invocation means one Python `call` trace event for the exact target
function, and target invocations are numbered 1-based in chronological event
order. Include the `call` event that opens target invocation 1 itself, followed
by every `call` event for a function in the tracked set that occurs while that
target invocation remains on the call stack, including nested/transitive calls
such as calls made by another tracked callee. Stop when that target invocation
returns. Exclude calls before it opens or after it returns, calls to every
function outside the exact tracked set (including builtins and library
functions), and non-`call` events. Preserve every repeated call; perform no
deduplication. If a tracked generator or coroutine were resumed and Python
delivered another `call` event for that resumption, it would count as another
entry under the same rule.

Order entries by the actual serial order in which Python delivers the `call`
events, earliest first. Trace events are delivered one at a time, so this is a
total order with no timestamp sorting or tie-breaker; do not sort by function
name or file. Function identity must be the fully dotted
`module.Class.method` or `module.function` qualname, including `<locals>` for a
nested function (for example, `sample.pkg.Widget.run`). The `file` value for
every entry must be the POSIX, repository-relative path
`kedro/framework/cli/starters.py`, not an absolute path. Function names and
file paths are plain JSON strings; do not apply `repr()` or add representation
quotes.

The complete answer must be one JSON object with exactly the shape
`{"function_call_order": [{"file": "str", "func": "str"}]}`.
`function_call_order` is a JSON array in the chronological order just defined,
and each element has exactly the two JSON-string fields `file` and `func`.
The `"str"` values in the displayed shape are type placeholders, not answer
values. Include no additional keys or fields."""


def _read_call_order(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    target_depth = 0
    completed_first_invocation = False
    calls: list[dict[str, str]] = []
    seen_functions: set[str] = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")
        raw_func = match.group("func")
        func = RAW_TO_CANONICAL.get(raw_func, raw_func)
        event = match.group("event")
        if not file_name.endswith(f"/{TARGET_FILE}"):
            continue
        if func == TARGET_FUNC:
            target_events += 1

        if completed_first_invocation:
            continue

        if func == TARGET_FUNC and event == "call":
            if target_depth == 0:
                target_depth = 1
                calls.append({"file": TARGET_FILE, "func": func})
                seen_functions.add(func)
            else:
                target_depth += 1
                calls.append({"file": TARGET_FILE, "func": func})
                seen_functions.add(func)
            continue

        if target_depth > 0 and event == "call" and func in TRACKED_FUNCS:
            calls.append({"file": TARGET_FILE, "func": func})
            seen_functions.add(func)

        if func == TARGET_FUNC and event == "return" and target_depth > 0:
            target_depth -= 1
            if target_depth == 0:
                completed_first_invocation = True

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not completed_first_invocation:
        raise RuntimeError("the first target invocation did not complete in the trace")
    if not calls:
        raise RuntimeError("no tracked call events were captured")
    missing = sorted(TRACKED_FUNCS - seen_functions)
    if missing:
        raise RuntimeError(f"trace did not capture tracked functions: {missing}")

    return {"function_call_order": calls}


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": _read_call_order(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
