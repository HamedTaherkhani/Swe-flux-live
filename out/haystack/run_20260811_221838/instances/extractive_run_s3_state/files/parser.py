import argparse
import ast
import json
from pathlib import Path


TARGET_FUNC = "haystack.components.readers.extractive.ExtractiveReader.run"
TRACE_FUNC = "haystack.components.readers.extractive.run"
TARGET_FILE = "haystack/components/readers/extractive.py"
OBSERVATION_EVENT_LINE = 627

QUESTION = """Run only `haystack_qa/extractive_run_s3_state/files/testcase.py::TestExtractiveRunProgramState::test_batched_logits_accumulate_from_generated_documents`. During that test run, consider the first invocation of `haystack.components.readers.extractive.ExtractiveReader.run` in `haystack/components/readers/extractive.py`. An invocation means a `call` of that exact function, numbered from 1 in chronological order.

Report the full ordered history of the local variable `cur_start_logits` immediately after line 626 has executed each time during that first invocation. More precisely, step k is the value present after the k-th chronological execution of absolute, 1-based source line 626 in the named file; line 626 is the assignment `cur_start_logits = output.start_logits`. For Python statements or expressions spanning multiple physical lines, an executed line is identified by the absolute, 1-based line on which that statement or expression begins. Decorator, `def`, and docstring lines are not observation points here.

Return exactly `{"value_history": [{"step": <int>, "value": <str>}, ...]}`. Preserve chronological execution order, number `step` from 1, do not sort by value, do not remove duplicates, and include one entry for every execution of line 626 in the first invocation. Each `value` must be Python `repr(cur_start_logits)` evaluated at that observation point, not `str()`. For any container, this means the `repr` of the whole container rather than element-by-element JSON conversion: strings retain quotes, and Python spellings such as `None` and `True` are retained. Embedded newlines in a repr are actual newline characters in the JSON string (for example, a Python value containing `x`, a newline, and `y` would be represented by a JSON string whose decoded value contains that newline). The variable is bound at every requested observation point, so there is no missing-value or JSON-null case."""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.exists():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    target_lines = [
        line
        for line in lines
        if TARGET_FILE in line and f" {TRACE_FUNC} event=" in line
    ]
    if not target_lines:
        raise SystemExit(f"ERROR: trace contains zero events for {TARGET_FUNC}")

    invocation_count = sum(f" {TRACE_FUNC} event=call " in line for line in target_lines)
    if invocation_count != 1:
        raise SystemExit(
            f"ERROR: expected exactly one invocation of {TARGET_FUNC}, found {invocation_count}"
        )

    values = []
    location = f"{TARGET_FILE}:{OBSERVATION_EVENT_LINE}"
    for line in target_lines:
        if location not in line or f" {TRACE_FUNC} event=line " not in line:
            continue
        marker = " locals="
        if marker not in line:
            raise SystemExit(f"ERROR: observation event has no locals payload: {line}")
        try:
            local_values = ast.literal_eval(line.split(marker, 1)[1])
        except (SyntaxError, ValueError) as exc:
            raise SystemExit(f"ERROR: cannot parse locals at observation event: {exc}") from exc
        if "cur_start_logits" not in local_values:
            raise SystemExit(
                "ERROR: cur_start_logits is absent immediately after an execution of line 626"
            )
        values.append(local_values["cur_start_logits"])

    if not values:
        raise SystemExit(
            f"ERROR: found no post-line-626 observation events for {TARGET_FUNC}"
        )

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"value_history": [{"step": "int", "value": "str"}]},
        "oracle_answer": {
            "value_history": [
                {"step": step, "value": value}
                for step, value in enumerate(values, start=1)
            ]
        },
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path} with {len(values)} history steps")


if __name__ == "__main__":
    main()
