#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "lark.tree_matcher.TreeMatcher._build_recons_rules"
TARGET_FILE_SUFFIX = "/lark/tree_matcher.py"

PREDICATES = {
    "len(recons_exp) == len(r.expansion)": 138,
    "len(rules) % 2 == 0": 120,
    "r.alias is None or not (r.options.expand1 and len(r.expansion) == 3)": 125,
    "r.options.expand1": 141,
    "sym.name not in seen": 147,
    "sym.name.startswith('_')": 151,
}

QUESTION = """Run every test method in `lark_qa/tree_matcher_build_recons_rules_m7_invariants/files/testcase.py::TestBuildReconsRulesInvariants` and aggregate the observations from all 12 methods. A contributing method is any method in that class whose name starts with `test_`; its pytest id is `lark_qa/tree_matcher_build_recons_rules_m7_invariants/files/testcase.py::TestBuildReconsRulesInvariants::<method-name>`. Method execution order does not affect the requested totals.

For the target function `lark.tree_matcher.TreeMatcher._build_recons_rules` in the repository-relative file `lark/tree_matcher.py`, evaluate each candidate predicate at its own observation point below. An observation point is a Python `line` event in the target function's own frame, immediately before Python executes the indicated source line. Line numbers are absolute, 1-based numbers in that repository file. For a multi-line statement, Python attributes the event to the line where the currently executed expression begins. The undecorated `def` line and the docstring line contribute only if Python actually emits a `line` event for them; do not synthesize an event for either. Do not count events in comprehension frames, events in callees, or `call`, `return`, and `exception` events. Generator resumptions do not themselves count; only matching `line` events count.

The candidate predicates and observation points are:

* `len(recons_exp) == len(r.expansion)` — line 138.
* `len(rules) % 2 == 0` — line 120.
* `r.alias is None or not (r.options.expand1 and len(r.expansion) == 3)` — line 125.
* `r.options.expand1` — line 141.
* `sym.name not in seen` — line 147.
* `sym.name.startswith('_')` — line 151.

Evaluate a predicate from the actual Python local objects in that target frame as they exist immediately before its line executes. Evaluate it once per matching line event, including repeated loop visits and visits after generator resumption. `observations` is the total number of evaluations summed across all contributing test methods. `violations` is the number whose Python truth value is false. `held_always` is exactly `violations == 0`, except that a predicate with zero observations must be reported as `observations: 0`, `violations: 0`, and `held_always: false`.

Return a JSON object with exactly one key, `invariant_report`. Its value is a list with one object per candidate, and every object has exactly these keys and JSON types: `held_always` (boolean), `observations` (integer), `predicate` (string copied verbatim from the candidate list), and `violations` (integer). Sort entries by the `predicate` string in ascending Unicode code-point order. Candidate strings are unique; if equal strings ever occurred, break the tie by ascending observation-point line number. Emit ordinary JSON booleans (`true` or `false`) and base-10 JSON integers; no runtime value is otherwise stringified, normalized, deduplicated, or omitted."""

EVENT_RE = re.compile(
    r"^.*? (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)
RULE_RE = re.compile(
    r"^ProbeRule\(origin=(?P<origin>.*?),alias=(?P<alias>.*?),"
    r"expand1=(?P<expand1>True|False),"
    r"expansion_len=(?P<expansion_len>\d+),"
    r"retained_len=(?P<retained_len>\d+)\)$"
)
NONTERMINAL_RE = re.compile(r"NonTerminal\((?P<name>'[^']*'|\"[^\"]*\")\)")


def parse_rule(value):
    match = RULE_RE.match(value)
    if not match:
        raise ValueError(f"cannot parse traced rule value: {value!r}")
    return {
        "alias": ast.literal_eval(match.group("alias")),
        "expand1": match.group("expand1") == "True",
        "expansion_len": int(match.group("expansion_len")),
        "retained_len": int(match.group("retained_len")),
    }


def parse_nonterminal_name(value):
    match = NONTERMINAL_RE.fullmatch(value)
    if not match:
        raise ValueError(f"cannot parse traced nonterminal value: {value!r}")
    return ast.literal_eval(match.group("name"))


def evaluate(predicate, state):
    if predicate == "len(recons_exp) == len(r.expansion)":
        rule = parse_rule(state["r"])
        return rule["retained_len"] == rule["expansion_len"]
    if predicate == "len(rules) % 2 == 0":
        return state["rules"].count("ProbeRule(") % 2 == 0
    if predicate == "r.alias is None or not (r.options.expand1 and len(r.expansion) == 3)":
        rule = parse_rule(state["r"])
        return (
            rule["alias"] is None
            or not (rule["expand1"] and rule["expansion_len"] == 3)
        )
    if predicate == "r.options.expand1":
        return parse_rule(state["r"])["expand1"]
    if predicate == "sym.name not in seen":
        sym_name = parse_nonterminal_name(state["sym"])
        seen_names = ast.literal_eval(state["seen"])
        if not isinstance(seen_names, set):
            raise ValueError(f"traced seen value is not a set: {state['seen']!r}")
        return sym_name not in seen_names
    if predicate == "sym.name.startswith('_')":
        return parse_nonterminal_name(state["sym"]).startswith("_")
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
    predicates_by_line = {line: predicate for predicate, line in PREDICATES.items()}
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
        event = match.group("event")
        try:
            local_changes = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"malformed locals in trace line: {raw_line}") from exc
        if not isinstance(local_changes, dict):
            raise ValueError(f"trace locals are not a dictionary: {raw_line}")

        if event == "call":
            state = {}
        state.update(local_changes)

        if event != "line":
            continue
        line_number = int(match.group("line"))
        predicate = predicates_by_line.get(line_number)
        if predicate is None:
            continue

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
            f"trace contains zero events for {TARGET_FUNC} in lark/tree_matcher.py"
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

    answer = build_answer(Path(args.trace_log))
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
        "oracle_answer": answer,
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
