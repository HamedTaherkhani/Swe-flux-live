#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "lark/parsers/xearley.py"
TARGET_FUNC = "lark.parsers.xearley.Parser._parse"
OBSERVATION_LINE = 163

QUESTION = (
    "Run every test method in the pytest class selection "
    "`lark_qa/xearley_parse_m3_state/files/testcase.py::"
    "TestXearleyParseProgramState` (that is, aggregate over all `test_...` "
    "methods in that class, each identified by its full pytest id and in the "
    "chronological order pytest executes them). Across all invocations of "
    "`lark.parsers.xearley.Parser._parse` in `lark/parsers/xearley.py`, collect "
    "the value of its local variable `node_cache` immediately before every "
    "execution of line 163, the statement beginning `if token == '\\n':`. "
    "This observation is after the call and assignments on line 161 have "
    "completed, so it records the dictionary returned by that iteration's "
    "nested `scan` call. Include observations from the `_parse` frame itself "
    "only; do not treat execution inside its nested `scan` function or any "
    "other callee as an observation. An invocation means one call of the "
    "target function during the selected test run, counted 1-based in "
    "chronological order, and an observation point means each chronological "
    "execution of line 163 within every such invocation. For each observation, "
    "apply Python `repr()` to the whole `node_cache` dictionary at that point; "
    "use Python spellings inside that string, preserve dictionary insertion "
    "order as `repr()` does, and do not separately repr or reorder its members. "
    "For example, a hypothetical dictionary would be represented as "
    "\"{'sample': 2}\", not as JSON object syntax. An empty dictionary is the "
    "string \"{}\", never JSON null and never an omitted value. Remove duplicate "
    "repr strings by exact string equality across all observation points, then "
    "sort the remaining strings ascending by Python's ordinary string order "
    "(lexicographic Unicode code-point order, with no secondary tie-breaker). "
    "Return exactly `{\"unique_values\": [<str>, ...]}`. Line numbers are "
    "absolute, 1-based source line numbers in the named repository file as it "
    "exists for this run. For a multi-line statement or expression, execution "
    "is attributed to the line where it begins; decorator, `def`, and docstring "
    "lines count only if Python executes them as line events."
)

EVENT_RE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    call_count = 0
    current_locals = None
    observed = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if " locals=" not in raw_line:
            raise RuntimeError(f"target event has no locals payload: {raw_line}")
        locals_text = raw_line.rsplit(" locals=", 1)[1]
        try:
            changed_locals = ast.literal_eval(locals_text)
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed_locals, dict):
            raise RuntimeError(f"target locals payload is not a dict: {raw_line}")

        event = match.group("event")
        if event == "call":
            if current_locals is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            call_count += 1
            current_locals = {}

        if current_locals is None:
            raise RuntimeError(f"target event outside an invocation: {raw_line}")
        current_locals.update(changed_locals)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            value = current_locals.get("node_cache")
            if value is None:
                raise RuntimeError(
                    f"line {OBSERVATION_LINE} reached without local 'node_cache'"
                )
            if not isinstance(value, str):
                raise RuntimeError("traced repr of 'node_cache' is not a string")
            observed.append(value)

        if event == "return":
            current_locals = None

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if call_count == 0:
        raise RuntimeError(f"trace contains no calls of {TARGET_FUNC}")
    if current_locals is not None:
        raise RuntimeError("trace ended during a target invocation")
    if not observed:
        raise RuntimeError(
            f"no line-{OBSERVATION_LINE} node_cache observations were found"
        )

    unique_values = sorted(set(observed))
    if len(unique_values) < 8:
        raise RuntimeError(
            f"expected at least 8 distinct node_cache values, got {len(unique_values)}"
        )
    return {"unique_values": unique_values}


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": parse_trace(Path(args.trace_log)),
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {output_path}")


if __name__ == "__main__":
    main()
