from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/config/omegaconf_config.py"
TARGET_FUNC = "kedro.config.omegaconf_config._check_duplicates"
VARIABLES = ("duplicates", "sorted_keys")
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* "
    r"locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run
`PYTHONHASHSEED=0 pytest --no-cov -rA -s kedro_qa/omegaconf_config_check_duplicates_m3_state/files/testcase.py::TestGeneratedDuplicateState::test_catalog_pair_matrix`
against this repository. During that complete test run, consider every
invocation of the exact function
`kedro.config.omegaconf_config.OmegaConfigLoader._check_duplicates` in
`kedro/config/omegaconf_config.py`. What is the sorted set of distinct values
taken by either local variable `duplicates` or local variable `sorted_keys` at
the observation events defined below?

An invocation is one call of that exact function, numbered 1-based in
chronological call order; all invocations during the test count. Only the exact
target function's own frame counts. Frames of callees, comprehensions, and
other nested code are excluded. For each target invocation, an observation
event is: (1) function entry, before its first body statement; (2) immediately
before every source line that Python executes in that frame; (3) immediately
when an exception event is delivered to that frame, before exception handling
or unwinding continues; or (4) immediately before that frame returns or
unwinds. At each event, inspect each of the two named locals only if it is
already bound. A mutation of the list held by `duplicates` therefore produces
the whole list's new state at the next observation event; do not report a
separate mutation operation.

Line numbers, if used to reproduce these events, are absolute, 1-based source
line numbers in the named file as it exists in this repository. For a
multi-line statement or expression, a line event occurs on the source line
where the executed portion begins, following Python's line-event behavior.
The function's `def` line may identify the function-entry event, but decorator
and docstring lines are not body-line events. No line number is part of the
answer.

Convert each observed value independently with Python `repr()` at that moment.
For a container, use `repr()` of the whole container in its current iteration
order, without recursively converting it to JSON and without reordering it.
Thus a string value includes its quote characters, and Python spellings such
as `None` and `True` remain inside container representations. Both locals are
unbound at some early events; skip an unbound local rather than emitting an
empty string, JSON `null`, or any placeholder. A bound empty list is a real
value and its `repr()` is retained.

Deduplicate the resulting repr strings across both variables, all observation
events, and all invocations, retaining one copy of each distinct string. Sort
them in ascending lexicographic order by Unicode code point, with no secondary
key needed because duplicates have been removed. The complete answer must
have exactly the JSON shape `{"unique_values": ["str"]}` where
`unique_values` is that sorted JSON array and `"str"` is a type placeholder,
not an answer value."""


def _validate_source(root: Path) -> None:
    source_path = root / TARGET_FILE
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_check_duplicates"
            and node.lineno == 513
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    assigned_names = {
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    missing = set(VARIABLES) - assigned_names
    if missing:
        raise RuntimeError(
            f"target no longer assigns expected locals: {', '.join(sorted(missing))}"
        )


def _read_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    call_events = 0
    values: set[str] = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(
                f"/{TARGET_FILE}"
            )
        ):
            continue

        target_events += 1
        if match.group("event") == "call":
            call_events += 1
        try:
            observed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(observed_locals, dict):
            raise RuntimeError(f"target locals are not a dict: {raw_line}")

        for variable in VARIABLES:
            if variable in observed_locals:
                value = observed_locals[variable]
                if not isinstance(value, str):
                    raise RuntimeError(
                        f"trace repr for local {variable!r} is not a string"
                    )
                values.add(value)

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if call_events == 0:
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    if not values:
        raise RuntimeError("trace contains no observed values for target locals")
    return sorted(values)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    _validate_source(Path.cwd())
    unique_values = _read_unique_values(args.trace_log)
    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
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
