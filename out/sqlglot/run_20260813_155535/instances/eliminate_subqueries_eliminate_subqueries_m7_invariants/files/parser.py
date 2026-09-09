import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.optimizer.eliminate_subqueries.eliminate_subqueries"
TARGET_FILE = "sqlglot/optimizer/eliminate_subqueries.py"
MAIN_LINE = 101
ZERO_LINE = 44

PREDICATES = {
    "expression.find(exp.Limit) is None": 38,
    "len(existing_ctes) >= len(new_ctes)": MAIN_LINE,
    "len(new_ctes) % 3 != 1": MAIN_LINE,
    "new_cte is None": MAIN_LINE,
    "new_cte is not None": MAIN_LINE,
    "root is not None": ZERO_LINE,
}

QUESTION = """Run every test method in `sqlglot_qa/eliminate_subqueries_eliminate_subqueries_m7_invariants/files/testcase.py::TestEliminateSubqueriesInvariants` and aggregate observations across the entire class. The contributing pytest ids are the class prefix followed by each of `test_alias_and_table_name_collisions`, `test_create_table_as_select`, `test_deep_nested_chain`, `test_distinct_derived_join_fanout`, `test_existing_ctes_with_nested_sources`, `test_insert_select_source`, `test_lateral_correlated_sources`, `test_mixed_unique_and_repeated_shapes`, `test_parenthesized_root_subquery`, `test_periodic_duplicate_fanout`, `test_recursive_cte_and_derived_tail`, and `test_union_of_generated_branches`; count their runtime events in pytest's chronological execution order.

For `sqlglot.optimizer.eliminate_subqueries.eliminate_subqueries` in `sqlglot/optimizer/eliminate_subqueries.py`, evaluate the following candidate predicates verbatim:

- `len(existing_ctes) >= len(new_ctes)`
- `len(new_ctes) % 3 != 1`
- `new_cte is None`
- `new_cte is not None`
- `expression.find(exp.Limit) is None`
- `root is not None`

For the two `len(...)` predicates and the two `new_cte` predicates, the observation point is every Python `line` event at absolute 1-based line 101 in the named repository file, immediately before the statement beginning on that line executes. For `expression.find(exp.Limit) is None`, the observation point is every Python `line` event at absolute 1-based line 38, immediately before the call beginning there executes; `exp.Limit` means the `sqlglot.expressions.Limit` class, and `find` has its repository-defined runtime semantics. For `root is not None`, the observation point is every Python `line` event at absolute 1-based line 44, immediately before its `return` executes. For a multi-line statement, a line event belongs to the absolute line on which that statement or expression begins. The function's `def` line, decorator lines, and docstring-only lines are not observation points. At each observation, evaluate the predicate against that invocation's current Python local objects, using ordinary Python identity, `len`, comparison, remainder, method-call, and boolean semantics. An invocation means one `call` of this exact function, including recursive direct calls, numbered 1-based in chronological order. Events in callees, comprehension frames, and all other functions do not count.

For each predicate, report `predicate` as the exact string above, `observations` as the total number of executions of that predicate's stated observation point across all listed methods and invocations, `violations` as the number of those evaluations that were false, and `held_always` as exactly `violations == 0` when at least one observation exists. If an observation point is never reached, report `observations: 0`, `violations: 0`, and `held_always: false`. Do not deduplicate repeated observations.

Return exactly `{"invariant_report": [...]}`. Each list entry has exactly `held_always` (JSON boolean), `observations` (JSON integer), `predicate` (JSON string), and `violations` (JSON integer). Sort entries by the exact `predicate` string in ascending Unicode code-point order; predicate strings are unique, so no further tie-break is needed. Values are native JSON values, not `repr()` or `str()` renderings; for example, a boolean is serialized as `true`, not the Python spelling `True`."""


EVENT_RE = re.compile(
    rf" (?P<file>\S*{re.escape(TARGET_FILE)}):(?P<line>\d+) "
    rf"{re.escape(TARGET_FUNC)} event=(?P<event>\w+)"
)


def _parse_locals(line):
    marker = " locals="
    if marker not in line:
        raise ValueError(f"target event has no locals payload: {line}")
    try:
        value = ast.literal_eval(line.rsplit(marker, 1)[1])
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"invalid locals payload: {line}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"locals payload is not a dictionary: {line}")
    return value


def _container_size(value, opening, closing):
    if not isinstance(value, str) or not value.startswith(opening) or not value.endswith(closing):
        raise ValueError(f"cannot count container repr: {value!r}")
    if value == opening + closing:
        return 0

    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    quote = None
    escaped = False
    commas = 0

    for char in value:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"'):
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                raise ValueError(f"unbalanced container repr: {value!r}")
        elif char == "," and len(stack) == 1:
            commas += 1

    if stack or quote:
        raise ValueError(f"unterminated container repr: {value!r}")
    return commas + 1


def _evaluate(predicate, local_values):
    if predicate == "expression.find(exp.Limit) is None":
        return "Limit(" not in local_values["expression"]
    if predicate == "new_cte is None":
        return local_values["new_cte"] == "None"
    if predicate == "new_cte is not None":
        return local_values["new_cte"] != "None"
    if predicate == "root is not None":
        return local_values["root"] != "None"

    new_ctes_size = _container_size(local_values["new_ctes"], "[", "]")
    if predicate == "len(new_ctes) % 3 != 1":
        return new_ctes_size % 3 != 1
    if predicate == "len(existing_ctes) >= len(new_ctes)":
        existing_size = _container_size(local_values["existing_ctes"], "{", "}")
        return existing_size >= new_ctes_size
    raise ValueError(f"unknown predicate: {predicate}")


def build_report(trace_text):
    frames = []
    target_events = 0
    counts = {
        predicate: {"observations": 0, "violations": 0} for predicate in PREDICATES
    }

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            frames.append(dict(_parse_locals(raw_line)))
            continue
        if not frames:
            raise ValueError(f"target {event} event occurred without an active invocation")

        if event == "line":
            frames[-1].update(_parse_locals(raw_line))
            for predicate, observation_line in PREDICATES.items():
                if line_number == observation_line:
                    counts[predicate]["observations"] += 1
                    if not _evaluate(predicate, frames[-1]):
                        counts[predicate]["violations"] += 1
        elif event == "return":
            frames.pop()

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if frames:
        raise ValueError("trace ended with unfinished target invocations")

    return [
        {
            "held_always": values["observations"] > 0 and values["violations"] == 0,
            "observations": values["observations"],
            "predicate": predicate,
            "violations": values["violations"],
        }
        for predicate, values in sorted(counts.items())
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    try:
        report = build_report(trace_text)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

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
        "oracle_answer": {"invariant_report": report},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
