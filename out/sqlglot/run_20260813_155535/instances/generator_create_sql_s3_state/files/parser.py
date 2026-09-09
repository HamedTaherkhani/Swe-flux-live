import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.generator.Generator.create_sql"
OBSERVATION_LINE = 1437
INVOCATION = 17
VARIABLES = (
    "expression_sql",
    "index_sql",
    "modifiers",
    "postalias_props_sql",
    "postexpression_props_sql",
    "properties_sql",
)

TRACE_PATTERN = re.compile(
    r"^\S+ \S+ (?P<file>.*):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the single pytest test method `CreateSQLProgramStateTest.test_programmatic_create_variants` in `sqlglot_qa/generator_create_sql_s3_state/files/testcase.py`. During that test run, consider the exact function `sqlglot.generator.Generator.create_sql` in `sqlglot/generator.py`.

Report the values of the local variables `expression_sql`, `index_sql`, `modifiers`, `postalias_props_sql`, `postexpression_props_sql`, and `properties_sql` immediately after the assignment to `expression_sql` whose statement begins on absolute line 1436 has executed in the 17th invocation of this exact function. Equivalently, this is the program state just before line 1437 executes in that invocation. An invocation means one `call` of this exact function during the test run, counted chronologically and 1-based; calls of overrides, callers, callees, or other functions are not invocations. Line numbers are absolute, 1-based line numbers in the named repository file. For a multi-line statement or expression, the executed line is the line where that statement or expression begins. Decorator, `def`, and docstring lines count only if Python executes them in this function's frame.

Return exactly `{"observed_state": [{"value": "...", "variable": "..."}]}` with six array elements. Each element has exactly the string keys `value` and `variable`; `variable` is the local's source name and `value` is Python's `repr()` of its value at that moment. For a container, use `repr()` of the whole container without recursively sorting or otherwise normalizing it: strings retain their quotes, and `None` and booleans use Python spellings (for example, `None` and `False`, not JSON `null` and `false`). Embedded newlines in a repr are real newline characters inside the JSON string. No requested local may be omitted, represented by JSON null, truncated, or replaced with a placeholder; if one does not exist at the observation point, the requested observation is invalid. Sort the six elements by `variable` in ascending Unicode code-point order and do not deduplicate them. Apply only the escaping required to serialize the repr strings as JSON."""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    state = {}
    observed = None

    for raw_line in trace_text.splitlines():
        match = TRACE_PATTERN.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as error:
            fail(f"could not parse locals from target trace event: {error}")
        if not isinstance(changed, dict):
            fail("target trace locals are not a dictionary")

        if event == "call":
            invocation += 1
            state = {}

        if invocation == INVOCATION:
            state.update(changed)
            if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
                missing = [variable for variable in VARIABLES if variable not in state]
                if missing:
                    fail(f"requested locals missing at observation point: {missing}")
                if observed is not None:
                    fail("observation point occurred more than once in the selected invocation")
                observed = [
                    {"value": state[variable], "variable": variable}
                    for variable in sorted(VARIABLES)
                ]

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation < INVOCATION:
        fail(f"trace contains only {invocation} calls of {TARGET_FUNC}")
    if observed is None:
        fail(
            f"line {OBSERVATION_LINE} was not reached in invocation {INVOCATION}"
        )

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": observed},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
