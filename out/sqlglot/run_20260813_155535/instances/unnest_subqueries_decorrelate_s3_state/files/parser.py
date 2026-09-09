import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.optimizer.unnest_subqueries.decorrelate"
POST_STATEMENT_LINE = 297
OCCURRENCE = 13
VARIABLES = ("group_by", "key_aliases", "nested", "predicate")

TRACE_PATTERN = re.compile(
    r"^\S+ \S+ (?P<file>.*):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the single pytest test method `CorrelatedProjectionStateTest.test_generated_correlated_projection` in `sqlglot_qa/unnest_subqueries_decorrelate_s3_state/files/testcase.py`. During that test run, consider `sqlglot.optimizer.unnest_subqueries.decorrelate` in `sqlglot/optimizer/unnest_subqueries.py`.

For the first invocation of `decorrelate`, report the values of the local variables `group_by`, `key_aliases`, `nested`, and `predicate` immediately after the statement `nested = exp.column(key_aliases[key], table_alias)` beginning on absolute line 295 has executed for the 13th time. An invocation means one call of this exact function during the test run; invocations and executions of the line are counted chronologically and 1-based. The 13th execution means the 13th completed evaluation of that assignment within this invocation's loop. Line numbers are absolute, 1-based line numbers in the named repository file. For a multi-line statement, its line is where the statement or expression begins; decorator, `def`, and docstring lines do not count unless Python executes them in the function frame.

Return exactly `{"observed_state": [{"value": "...", "variable": "..."}]}` with four array elements. Each element has exactly the string keys `value` and `variable`; `variable` is the local's source name and `value` is Python's `repr()` of its value at that moment. For a container, use `repr()` of the whole container without recursively sorting or otherwise normalizing it: strings retain quotes, and `None` and booleans use Python spellings (for example, `None` and `True`, not JSON `null` and `true`). Embedded newlines in a repr are real newline characters inside the JSON string. No requested local may be omitted or represented by JSON null; if one does not exist at the observation point, the requested observation is invalid. Sort the four elements by `variable` in ascending Unicode code-point order; do not deduplicate them. JSON escaping is applied only when serializing these repr strings."""


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
    occurrence = 0
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
            occurrence = 0

        if invocation == 1:
            state.update(changed)
            if event == "line" and int(match.group("line")) == POST_STATEMENT_LINE:
                occurrence += 1
                if occurrence == OCCURRENCE:
                    missing = [variable for variable in VARIABLES if variable not in state]
                    if missing:
                        fail(f"requested locals missing at observation point: {missing}")
                    observed = [
                        {"value": state[variable], "variable": variable}
                        for variable in sorted(VARIABLES)
                    ]

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation == 0:
        fail(f"trace contains no calls of {TARGET_FUNC}")
    if observed is None:
        fail(
            f"line {POST_STATEMENT_LINE} did not reach occurrence {OCCURRENCE} "
            "in the first invocation"
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
