from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/ipython/__init__.py"
TARGET_FUNC = "kedro.ipython._load_node"
TRACKED_FUNCS = {
    "kedro.ipython._NodeBoundArguments._find_var_positional_arg",
    "kedro.ipython._NodeBoundArguments.input_params_dict",
    "kedro.ipython._create_cell_with_text",
    "kedro.ipython._find_node",
    "kedro.ipython._format_node_inputs_text",
    "kedro.ipython._get_node_bound_arguments",
    "kedro.ipython._guess_run_environment",
    "kedro.ipython._load_node",
    "kedro.ipython._prepare_function_body",
    "kedro.ipython._prepare_function_call",
    "kedro.ipython._prepare_imports",
    "kedro.ipython._prepare_node_inputs",
    "kedro.ipython._print_cells",
    "kedro.ipython.load_ipython_extension",
    "kedro.ipython.magic_load_node",
}
RAW_TO_CANONICAL = {
    "kedro.ipython._find_var_positional_arg": (
        "kedro.ipython._NodeBoundArguments._find_var_positional_arg"
    ),
    "kedro.ipython.input_params_dict": (
        "kedro.ipython._NodeBoundArguments.input_params_dict"
    ),
}
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/ipython_load_node_m6_calls/files/testcase.py::TestIPythonLoadNodeCallGraph::test_generated_node_magic_calls`
against this repository. During the complete test run, which functions from
the tracked set below execute at least once? The primary target is
`kedro.ipython._load_node` in `kedro/ipython/__init__.py`.

The tracked set is exactly these fifteen functions:

1. `kedro.ipython._NodeBoundArguments._find_var_positional_arg`
2. `kedro.ipython._NodeBoundArguments.input_params_dict`
3. `kedro.ipython._create_cell_with_text`
4. `kedro.ipython._find_node`
5. `kedro.ipython._format_node_inputs_text`
6. `kedro.ipython._get_node_bound_arguments`
7. `kedro.ipython._guess_run_environment`
8. `kedro.ipython._load_node`
9. `kedro.ipython._prepare_function_body`
10. `kedro.ipython._prepare_function_call`
11. `kedro.ipython._prepare_imports`
12. `kedro.ipython._prepare_node_inputs`
13. `kedro.ipython._print_cells`
14. `kedro.ipython.load_ipython_extension`
15. `kedro.ipython.magic_load_node`

A tracked function is covered if Python begins its exact function frame at
least once during the named test, meaning that exact frame produces a Python
`call` event. Count calls anywhere in the complete test run: a qualifying
frame may be entered directly by another listed function, transitively below
one, or from an otherwise unlisted caller. Merely being on the stack while
some other function runs does not cover a function; that listed function's
own exact frame must begin. Exclude every function outside the listed set,
including builtins and library functions, and ignore all non-`call` events.

Repeated calls do not create repeated answer entries: emit each covered
function exactly once. Recursion is handled identically, so one or many
recursive entries still produce one answer entry. If a tracked generator or
coroutine is resumed and Python reports another `call` event for that
resumption, it qualifies under the same rule but still does not create a
duplicate. Functions in the tracked set that have no qualifying event are
omitted.

Function identity is the fully dotted `module.Class.method` or
`module.function` qualname (for example, `sample.pkg.Widget.run`). Preserve
leading underscores and include `<locals>` if it is part of a qualname. Every
`file` value is the POSIX, repository-relative path of the function's source
file; for this tracked set it is `kedro/ipython/__init__.py`. These values are
plain JSON strings: use the names and paths themselves, not Python `repr()`
text and not additional representation quotes. No answer field may be absent,
empty, or JSON `null`.

The complete answer must have exactly the JSON shape
`{"covered_functions": [{"file": "str", "func": "str"}]}`.
`covered_functions` is a JSON array whose elements each have exactly the two
JSON-string fields `file` and `func`. Sort entries first by `file` in ascending
Unicode code-point order and then by `func` in ascending Unicode code-point
order. This is a total order for this deduplicated set; do not use call time,
call count, source line, or locale as a tie-breaker. The `"str"` values in the
displayed shape are type placeholders, not answer values. Include no
additional keys or fields."""


def _read_covered_functions(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    covered: set[tuple[str, str]] = set()

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
        if event == "call" and func in TRACKED_FUNCS:
            covered.add((TARGET_FILE, func))

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not covered:
        raise RuntimeError("trace contains no covered functions from the tracked set")

    return {
        "covered_functions": [
            {"file": file_name, "func": func}
            for file_name, func in sorted(covered)
        ]
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": _read_covered_functions(args.trace_log),
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
