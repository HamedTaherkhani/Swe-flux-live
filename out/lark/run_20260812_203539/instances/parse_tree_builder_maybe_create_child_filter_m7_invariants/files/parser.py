#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/parse_tree_builder.py"
TARGET_FUNC = "lark.parse_tree_builder.maybe_create_child_filter"
TEST_FILE = "lark_qa/parse_tree_builder_maybe_create_child_filter_m7_invariants/files/testcase.py"
TEST_CLASS = "TestGeneratedParseTreeBuilders"

PREDICATES = (
    "ambiguous == keep_all_tokens",
    "empty_indices[i] == 0",
    "keep_all_tokens or not (sym.is_term and sym.filter_out)",
    "len(to_include) == i",
    "nones_to_add >= 0",
    "not (ambiguous and i == 32)",
)


def fail(message):
    raise RuntimeError(message)


def locate_observation_lines(root):
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "maybe_create_child_filter"
        ),
        None,
    )
    if function is None:
        fail("could not locate maybe_create_child_filter")
    loop = next((node for node in function.body if isinstance(node, ast.For)), None)
    if loop is None:
        fail("could not locate target for-loop")
    condition = next((node for node in loop.body if isinstance(node, ast.If)), None)
    if condition is None or not condition.body:
        fail("could not locate inclusion condition")
    return condition.lineno, condition.body[0].lineno


def parse_value(raw, name):
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail("cannot decode traced local %s=%r: %s" % (name, raw, exc))


def read_events(trace_path):
    if not trace_path.is_file():
        fail("trace log is missing: %s" % trace_path)
    if trace_path.stat().st_size == 0:
        fail("trace log is empty: %s" % trace_path)
    event_re = re.compile(
        r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
        r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
        r".*?\slocals=(?P<locals>\{.*\})$"
    )
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_re.search(raw_line)
        if not match:
            continue
        filename = match.group("file").replace("\\", "/")
        if not filename.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail("cannot decode trace locals: %s" % exc)
        if not isinstance(changed, dict):
            fail("trace locals are not a dictionary")
        events.append((match.group("event"), int(match.group("line")), changed))
    if not events:
        fail("trace contains zero events for %s" % TARGET_FUNC)
    if not any(event == "call" for event, _, _ in events):
        fail("trace contains no call event for %s" % TARGET_FUNC)
    return events


def evaluate(events, observation_line, included_line):
    results = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in PREDICATES
    }
    state = {}
    pending = None
    completed_calls = 0

    def finish_pending(was_included):
        nonlocal pending
        if pending is None:
            return
        values = pending
        required = (
            "ambiguous",
            "empty_indices",
            "i",
            "keep_all_tokens",
            "nones_to_add",
            "to_include",
        )
        missing = [name for name in required if name not in values]
        if missing:
            fail("observation is missing locals: %s" % ", ".join(missing))
        ambiguous = parse_value(values["ambiguous"], "ambiguous")
        empty_indices = parse_value(values["empty_indices"], "empty_indices")
        i = parse_value(values["i"], "i")
        keep_all_tokens = parse_value(values["keep_all_tokens"], "keep_all_tokens")
        nones_to_add = parse_value(values["nones_to_add"], "nones_to_add")
        to_include = parse_value(values["to_include"], "to_include")
        truth = {
            "ambiguous == keep_all_tokens": ambiguous == keep_all_tokens,
            "empty_indices[i] == 0": empty_indices[i] == 0,
            "keep_all_tokens or not (sym.is_term and sym.filter_out)": was_included,
            "len(to_include) == i": len(to_include) == i,
            "nones_to_add >= 0": nones_to_add >= 0,
            "not (ambiguous and i == 32)": not (ambiguous and i == 32),
        }
        for predicate in PREDICATES:
            results[predicate]["observations"] += 1
            if not truth[predicate]:
                results[predicate]["violations"] += 1
        pending = None

    in_call = False
    for event, line, changed in events:
        if event == "call":
            if in_call:
                fail("overlapping target invocations are not supported")
            finish_pending(False)
            state = {}
            state.update(changed)
            in_call = True
            continue
        if not in_call:
            continue
        if event == "line":
            if pending is not None:
                finish_pending(line == included_line)
            state.update(changed)
            if line == observation_line:
                pending = dict(state)
        elif event == "return":
            finish_pending(False)
            completed_calls += 1
            in_call = False
            state = {}
        elif event == "exception":
            state.update(changed)

    if in_call:
        fail("trace ended during a target invocation")
    if completed_calls == 0:
        fail("trace contains no completed target invocation")
    if not any(item["observations"] for item in results.values()):
        fail("the stated observation point was never reached")

    report = []
    for predicate in sorted(PREDICATES):
        observations = results[predicate]["observations"]
        violations = results[predicate]["violations"]
        report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": report}


def build_question(observation_line):
    candidates = "; ".join("`%s`" % predicate for predicate in PREDICATES)
    return (
        "Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, pytest selection "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate over ALL test methods in that "
        "class. Pytest identifies them as that file-and-class prefix followed by each "
        "method name, and runs them in source-definition order; counts are totals over "
        "the complete class run, so method boundaries do not reset them. During this run, "
        f"consider every invocation of `{TARGET_FUNC}` in `{TARGET_FILE}`. An invocation "
        "is one call of that function, numbered 1-based in chronological call order across "
        "the complete run. The observation point is the `line` event in the target "
        f"function's own frame at absolute, 1-based line {observation_line}, immediately "
        "before Python evaluates the `if keep_all_tokens ...` statement, once for each "
        "execution of that line. Evaluate all six candidate predicates at every such "
        "observation using the local values that exist at that instant and ordinary Python "
        "expression semantics: "
        f"{candidates}. Attribute access in the third predicate uses the runtime `sym` "
        "object's actual attributes. Count only this exact function frame; exclude callees, "
        "comprehension frames, and every other frame. Source lines are those of the named "
        "repository file as it exists for this run. For a multi-line statement or expression, "
        "an executed line is the absolute line where that statement or expression begins; "
        "the `def` line, decorators, and comments are not observations. For each predicate, "
        "`observations` is the number of times it was evaluated, and `violations` is the "
        "number of those evaluations whose result was false. `held_always` is true exactly "
        "when `observations` is greater than zero and `violations == 0`; if a predicate has "
        "zero observations, report 0 observations, 0 violations, and false for `held_always`. "
        "Do not deduplicate observations or predicates. Return exactly one JSON object with "
        "the single key `invariant_report`, whose value is a JSON array containing one object "
        "per stated predicate. Each object has exactly the keys `held_always` (JSON boolean), "
        "`observations` (JSON integer), `predicate` (JSON string copied verbatim from the "
        "candidate expression without backticks), and `violations` (JSON integer). Within each "
        "object use those keys in that order. Sort the array by the `predicate` string ascending "
        "using Unicode code-point order; exact duplicate predicate strings, if any, would retain "
        "their original stated order as the tie-break, though none are stated here. Use ordinary "
        "JSON spelling (`true`/`false`, not Python `True`/`False`), with no additional keys, "
        "normalization, value formatting, or string representations."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    observation_line, included_line = locate_observation_lines(root)
    events = read_events(Path(args.trace_log))
    answer = evaluate(events, observation_line, included_line)
    payload = {
        "question_kind": "M7_Invariants",
        "question": build_question(observation_line),
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
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise
