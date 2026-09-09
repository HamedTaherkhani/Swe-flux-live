from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/startup.py"
TARGET_FUNC = "kedro.framework.startup._get_project_metadata"
OBSERVATION_LINE = 102
OCCURRENCE = 17
VARIABLES = ("metadata_dict", "project_path", "pyproject_toml", "source_dir")
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* "
    r"locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test
`kedro_qa/startup_get_project_metadata_s3_state/files/testcase.py::TestBootstrapMetadataState::test_generated_project_matrix`
against this repository. In the exact function frame
`kedro.framework.startup._get_project_metadata` from
`kedro/framework/startup.py`, what are the values of the local variables
`metadata_dict`, `project_path`, `pyproject_toml`, and `source_dir` immediately
after line 102 has executed for the 17th time during the test run?

Line numbers are absolute, 1-based source line numbers in the named file as it
exists in this repository. Here, one execution of line 102 means one normal
completion, in an exact target-function frame, of the assignment statement
whose first source line is 102. Count those completions 1-based in chronological
order across all calls made during the test, and observe the state after that
assignment has taken effect but before the next executable statement in that
frame begins. Only executions in the exact target frame count; activity in
callees, comprehensions, or other nested frames does not count. In general, a
multi-line statement is identified by the absolute line where the statement
begins. A function's `def` line, decorator lines, and docstring lines are not
executions of body statements and do not count.

Report each value as the string produced by Python `repr()` at that moment.
For a container, use `repr()` of the whole container, without recursively
converting it to JSON or reordering it. Thus strings retain their quote
characters, Python spellings such as `None` and `True` remain inside the
reported string, and any embedded newline is a real newline character in the
JSON string after JSON decoding. Do not normalize path representations. All
four named locals exist at the observation point, so no missing-value or JSON
`null` convention is needed.

The complete answer must have exactly the JSON shape
`{"observed_state": [{"value": "str", "variable": "str"}]}`. The
`observed_state` value is a JSON array containing one object for each of the
four named variables. Each object has exactly the string keys `value` and
`variable`; `variable` is the local's source name and `value` is its `repr()`
string. Sort the objects by `variable` in ascending Unicode code-point order.
Retain all four entries and do not deduplicate them. The `"str"` strings in the
shape example are type placeholders, not answer values."""


def _validate_source(root: Path) -> None:
    source_path = root / TARGET_FILE
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_get_project_metadata"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")
    assignments = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.Assign) and node.lineno == OBSERVATION_LINE
    ]
    if len(assignments) != 1:
        raise RuntimeError(
            f"expected exactly one assignment on line {OBSERVATION_LINE}"
        )


def _read_observed_state(trace_path: Path) -> dict[str, str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    occurrence = 0
    current: dict[str, str] | None = None
    awaiting_post_state = False

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
        event = match.group("event")
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed_locals, dict):
            raise RuntimeError(f"target locals are not a dict: {raw_line}")

        if event == "call":
            if current is not None:
                raise RuntimeError("nested target call encountered")
            current = {}
        if current is None:
            raise RuntimeError(f"target {event} event appeared outside a call")
        current.update(changed_locals)

        if awaiting_post_state:
            missing = [name for name in VARIABLES if name not in current]
            if missing:
                raise RuntimeError(
                    f"observation state is missing locals: {', '.join(missing)}"
                )
            observed = {name: current[name] for name in VARIABLES}
            if any(value.endswith("...") for value in observed.values()):
                raise RuntimeError("an observed repr appears to be truncated")
            return observed

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            occurrence += 1
            if occurrence == OCCURRENCE:
                awaiting_post_state = True

        if event == "return":
            current = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    raise RuntimeError(
        f"trace contains only {occurrence} executions of line "
        f"{OBSERVATION_LINE}; need {OCCURRENCE}"
    )


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    _validate_source(Path.cwd())
    observed = _read_observed_state(args.trace_log)
    observed_state = [
        {"value": observed[variable], "variable": variable}
        for variable in sorted(VARIABLES)
    ]
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": observed_state},
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
