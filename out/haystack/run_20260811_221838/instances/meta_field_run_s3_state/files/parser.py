#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "haystack/components/rankers/meta_field.py"
TARGET_FUNC = "haystack.components.rankers.meta_field.MetaFieldRanker.run"
TRACE_FUNC = "haystack.components.rankers.meta_field.run"
TARGET_LINE = 318
TARGET_OCCURRENCE = 1
VARIABLES = (
    "docs_missing_meta_field",
    "parsed_meta",
    "reverse",
    "warning_start",
)

QUESTION = """Run only `haystack_qa/meta_field_run_s3_state/files/testcase.py::TestMetaFieldRunProgramState::test_generated_mixed_metadata_linear_merge`. During that test run, consider the first invocation of `haystack.components.rankers.meta_field.MetaFieldRanker.run` in `haystack/components/rankers/meta_field.py`. An invocation means one `call` of that exact function; invocations are numbered from 1 in chronological order.

Report the values of the local variables `docs_missing_meta_field`, `parsed_meta`, `reverse`, and `warning_start` immediately after line 318 has executed for the first time in that invocation and before the next statement in that frame executes. Occurrence 1 means the first chronological execution of the statement whose expression begins at absolute, 1-based source line 318 in the named repository file. For a multi-line statement or expression, its executed-line number is the absolute, 1-based line where that statement or expression begins. Decorator lines, the `def` line, and docstring lines are not observation points unless Python executes them in this invocation.

Return exactly `{"observed_state": [{"value": <str>, "variable": <str>}, ...]}`. `observed_state` must contain exactly one object for each of the four requested locals, sorted by `variable` in ascending Unicode code-point order, with no deduplication. Each object has exactly the two JSON string fields shown. `variable` is the source-level local name. `value` is Python's exact `repr()` string for the complete local value at the observation point, not `str()` and not an element-by-element JSON conversion. Thus a container is represented by the `repr()` of the whole container, strings inside representations retain Python quote characters, and Python spellings such as `None` and `True` are retained. Character escaping is exactly that produced by `repr()`; for example, the repr of a string containing `left`, a newline, and `right` contains the two characters backslash and `n`, and JSON serialization escapes that backslash as required while the decoded JSON value remains the repr text. All four locals are bound at this point, so neither an absent key nor JSON `null` represents a missing value."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)(?: |$)"
)


def parse_args():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    return argument_parser.parse_args()


def parse_changed_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        raise ValueError(f"target event has no locals payload: {raw_line.rstrip()}")
    try:
        parsed = ast.literal_eval(raw_line.split(marker, 1)[1].strip())
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"cannot parse target locals payload: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("target locals payload is not a dictionary")
    if not all(isinstance(name, str) and isinstance(value, str) for name, value in parsed.items()):
        raise ValueError("target locals payload does not map names to repr strings")
    return parsed


def harvest(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    occurrence = 0
    current_locals = {}
    waiting_for_post_line_event = False
    observed = None

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if (
                not match
                or match.group("func") != TRACE_FUNC
                or TARGET_FILE not in match.group("file")
            ):
                continue

            target_events += 1
            event = match.group("event")
            line_number = int(match.group("line"))
            changed_locals = parse_changed_locals(raw_line)

            if event == "call":
                invocation += 1
                current_locals = {}
                occurrence = 0
                waiting_for_post_line_event = False

            if invocation != 1:
                continue

            current_locals.update(changed_locals)
            if waiting_for_post_line_event:
                missing = [variable for variable in VARIABLES if variable not in current_locals]
                if missing:
                    raise ValueError(f"observation is missing requested locals: {missing}")
                observed = [
                    {"value": current_locals[variable], "variable": variable}
                    for variable in sorted(VARIABLES)
                ]
                break

            if event == "line" and line_number == TARGET_LINE:
                occurrence += 1
                if occurrence == TARGET_OCCURRENCE:
                    waiting_for_post_line_event = True

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if occurrence < TARGET_OCCURRENCE:
        raise ValueError(
            f"line {TARGET_LINE} executed only {occurrence} times in the first invocation"
        )
    if observed is None:
        raise ValueError(f"trace ended before state after line {TARGET_LINE} was observable")
    if any(item["value"].endswith("...") for item in observed):
        raise ValueError("an observed repr was truncated by the trace logger")
    return observed


def main():
    args = parse_args()
    output_path = Path(args.out)
    observed = harvest(Path(args.trace_log))
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path} with {len(observed)} observed locals")


if __name__ == "__main__":
    main()
