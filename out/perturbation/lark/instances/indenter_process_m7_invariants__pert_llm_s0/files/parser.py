#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "lark.indenter.Indenter._process"
TARGET_FILE_SUFFIX = "/lark/indenter.py"

PREDICATES = {
    "len(self.indent_level) == self.paren_level + 1": 62,
    "self.paren_level % 2 == 0": 65,
    "self.paren_level < 2": 68,
    "self.paren_level == 0": 61,
    "token.type not in self.CLOSE_PAREN_types": 61,
    "token.type == self.NL_type": 61,
}

QUESTION = """Run every test method in `lark_qa/indenter_process_m7_invariants/files/testcase.py::TestIndenterProcessInvariants` and aggregate observations across all 12 methods. A contributing method is every method in that class whose name starts with `test_`; its pytest id is `lark_qa/indenter_process_m7_invariants/files/testcase.py::TestIndenterProcessInvariants::<method-name>`. Counts are totals across the whole class, and neither pytest's method execution order nor generator interleaving changes those totals.

For the target generator function `lark.indenter.Indenter._process` in the repository-relative file `lark/indenter.py`, evaluate the six candidate predicates below at their stated observation points. An observation is a Python `line` event in the target function's own generator frame, immediately before Python executes the named source line. Line numbers are absolute, 1-based numbers in that repository file as checked out. For a multi-line statement or expression, Python attributes the event to the line where that currently executed statement or expression begins. Do not synthesize events for the undecorated `def` line or any docstring. Count only matching `line` events: exclude `call`, `return`, and `exception` events, events in `handle_NL` or any other callee, and events in comprehension frames. A generator resumption is not itself an observation, but a matching line event after resumption is counted. Repeated visits to a line, including loop visits and visits after yields, are separate observations.

The candidate predicates and their observation points are:

* `len(self.indent_level) == self.paren_level + 1` — line 62, immediately before that line increments `self.paren_level`.
* `self.paren_level % 2 == 0` — line 65, immediately before the assertion on that line.
* `self.paren_level < 2` — line 68, immediately before that line pops one indentation level.
* `self.paren_level == 0` — line 61, immediately before the opener-membership test.
* `token.type not in self.CLOSE_PAREN_types` — line 61, immediately before the opener-membership test.
* `token.type == self.NL_type` — line 61, immediately before the opener-membership test.

Evaluate every predicate from the actual Python local objects in the target frame at that instant, using ordinary Python attribute access, `len`, comparison, remainder, and truth-value semantics. Predicates sharing line 61 are each evaluated once for every line event there. `observations` is the number of evaluations summed across all contributing methods. `violations` is the number of those evaluations whose Python truth value is false. `held_always` is exactly `violations == 0` when `observations` is positive. A candidate whose line is never reached must instead be reported as `observations: 0`, `violations: 0`, and `held_always: false`.

Return a JSON object with exactly one key, `invariant_report`. Its value is a list containing one object per candidate predicate, with no deduplication or omission. Every object has exactly these keys and JSON types: `held_always` (boolean), `observations` (integer), `predicate` (string copied verbatim from the candidate list), and `violations` (integer). Sort the objects by `predicate` in ascending Unicode code-point order. Candidate strings are unique; if equal strings were present, the tie-break would be the observation-point line number in ascending numeric order. Emit ordinary JSON booleans (`true` and `false`) and base-10 JSON integers. Predicate strings are emitted as shown; no runtime value is represented with `repr`, `str`, JSON `null`, an empty string, a function name, or an exception name, and no other normalization is applied."""

EVENT_RE = re.compile(
    r"^.*? (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)
INDENTER_RE = re.compile(
    r"^ProbeIndenter\(paren_level=(?P<paren>-?\d+),"
    r"indent_level=(?P<indent>\[.*\])\)$"
)
TOKEN_RE = re.compile(r"^Token\((?P<type>.*?), (?P<value>.*)\)$")


def parse_indenter(value):
    match = INDENTER_RE.fullmatch(value)
    if not match:
        raise ValueError(f"cannot parse traced indenter value: {value!r}")
    indent_level = ast.literal_eval(match.group("indent"))
    if not isinstance(indent_level, list) or not all(
        isinstance(item, int) for item in indent_level
    ):
        raise ValueError(f"invalid traced indentation stack: {value!r}")
    return int(match.group("paren")), indent_level


def parse_token_type(value):
    match = TOKEN_RE.fullmatch(value)
    if not match:
        raise ValueError(f"cannot parse traced token value: {value!r}")
    token_type = ast.literal_eval(match.group("type"))
    if not isinstance(token_type, str):
        raise ValueError(f"invalid traced token type: {value!r}")
    return token_type


def evaluate(predicate, state):
    paren_level, indent_level = parse_indenter(state["self"])
    if predicate == "len(self.indent_level) == self.paren_level + 1":
        return len(indent_level) == paren_level + 1
    if predicate == "self.paren_level % 2 == 0":
        return paren_level % 2 == 0
    if predicate == "self.paren_level < 2":
        return paren_level < 2
    if predicate == "self.paren_level == 0":
        return paren_level == 0
    if predicate == "token.type not in self.CLOSE_PAREN_types":
        return parse_token_type(state["token"]) != "CLOSE"
    if predicate == "token.type == self.NL_type":
        return parse_token_type(state["token"]) == "NL"
    raise AssertionError(f"unknown predicate: {predicate}")


def build_answer(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"trace log is empty: {trace_path}")

    counts = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in PREDICATES
    }
    predicates_by_line = {}
    for predicate, line_number in PREDICATES.items():
        predicates_by_line.setdefault(line_number, []).append(predicate)

    state = {}
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if (
            match.group("func") != TARGET_FUNC
            or not match.group("file").endswith(TARGET_FILE_SUFFIX)
        ):
            continue

        target_events += 1
        try:
            local_changes = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"malformed locals in trace line: {raw_line}") from exc
        if not isinstance(local_changes, dict):
            raise ValueError(f"trace locals are not a dictionary: {raw_line}")

        if match.group("event") == "call":
            state = {}
        state.update(local_changes)
        if match.group("event") != "line":
            continue

        line_number = int(match.group("line"))
        for predicate in predicates_by_line.get(line_number, []):
            try:
                held = bool(evaluate(predicate, state))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"cannot evaluate {predicate!r} at target line {line_number}"
                ) from exc
            counts[predicate]["observations"] += 1
            if not held:
                counts[predicate]["violations"] += 1

    if target_events == 0:
        raise ValueError(
            f"trace contains zero events for {TARGET_FUNC} in lark/indenter.py"
        )

    report = []
    for predicate in sorted(PREDICATES):
        observations = counts[predicate]["observations"]
        violations = counts[predicate]["violations"]
        report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": report}


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {
                    "held_always": "bool",
                    "observations": "int",
                    "predicate": "str",
                    "violations": "int",
                }
            ]
        },
        "oracle_answer": build_answer(Path(args.trace_log)),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
