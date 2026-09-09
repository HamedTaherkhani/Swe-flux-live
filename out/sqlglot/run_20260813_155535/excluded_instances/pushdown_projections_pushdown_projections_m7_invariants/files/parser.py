import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.optimizer.pushdown_projections.pushdown_projections"
COMMON_LINE = 155
ZERO_LINE = 110
PREDICATES = (
    "bool(name)",
    "isinstance(source, Scope)",
    "len(name) >= 2",
    "len(name) % 2 == 0",
    'not name.startswith("qunion")',
    'scope.expression.args.get("by_name") is True',
)
TRACE_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    + re.escape(TARGET_FUNC)
    + r" event=(?P<event>\w+)(?: .*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run every test method in `sqlglot_qa/pushdown_projections_pushdown_projections_m7_invariants/files/testcase.py::TestPushdownProjectionInvariants` and aggregate across all methods in that class whose names begin with `test_` (12 methods total). A test is identified by the pytest id `sqlglot_qa/pushdown_projections_pushdown_projections_m7_invariants/files/testcase.py::TestPushdownProjectionInvariants::<method_name>`; pytest runs these unittest methods in ascending method-name order. Analyze direct invocations of `sqlglot.optimizer.pushdown_projections.pushdown_projections` in `sqlglot/optimizer/pushdown_projections.py`. An invocation is one `call` of that exact function during the complete class run, numbered 1-based in chronological order; nested helper calls and calls to any other function do not create observations.

Evaluate these candidate predicates verbatim:
- `bool(name)`
- `isinstance(source, Scope)`
- `len(name) >= 2`
- `len(name) % 2 == 0`
- `not name.startswith("qunion")`
- `scope.expression.args.get("by_name") is True`

For the first five predicates, an observation is each Python `line` event at absolute, 1-based line 155 of `sqlglot/optimizer/pushdown_projections.py`, immediately before `if column_aliases:` is evaluated. Evaluate each predicate independently on the live local Python objects in the target frame at that event; in particular, `Scope` means `sqlglot.optimizer.scope.Scope`, `bool` and `len` have their normal Python semantics, unary `not` negates the resulting truth value, and `str.startswith` is case-sensitive. For the last predicate, an observation is each Python `line` event at absolute, 1-based line 110 in that file, immediately before the multi-line assignment beginning `scope_sql = ...`; evaluate it on the live `scope` local. Line numbers refer to the named repository file as provided. A line event occurs on the physical line where the next statement or expression begins; the function's `def` line, decorators, and docstring lines are not observations. Each execution of an observation line counts separately, including repeated executions within one invocation. Events in helper, comprehension, generator, or other frames are excluded.

For each predicate, `observations` is the total number of its observations over all test methods and invocations, and `violations` is the number at which evaluating it produces false. `held_always` is exactly `violations == 0` when `observations > 0`. A predicate with no observations is not evaluable and must instead be reported as `{"observations": 0, "violations": 0, "held_always": false}`. Do not deduplicate repeated observations.

Return `{"invariant_report": [...]}`. Each list item must contain exactly `predicate` (JSON string copied verbatim from the candidate list), `held_always` (JSON boolean), `observations` (JSON integer), and `violations` (JSON integer). Sort items by the `predicate` string in ascending Unicode code-point order; predicates are unique, so there is no further tie-break. JSON strings use JSON escaping, while predicate evaluation uses the actual Python values rather than `repr()` or `str()` serialization. For example only, a Python predicate text `value.endswith("z")` would be represented as the JSON string `"value.endswith(\\"z\\")"`."""


def parse_locals(raw):
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(f"cannot parse trace locals: {raw}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"trace locals are not a dictionary: {raw}")
    return value


def materialize(state, key):
    if key not in state:
        raise RuntimeError(f"missing local {key!r} at an observation")
    try:
        return ast.literal_eval(state[key])
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(f"cannot materialize local {key!r}: {state[key]}") from exc


def evaluate(predicate, state):
    if predicate == "bool(name)":
        return bool(materialize(state, "name"))
    if predicate == "isinstance(source, Scope)":
        source_repr = state.get("source")
        if source_repr is None:
            raise RuntimeError("missing local 'source' at an observation")
        return source_repr.startswith("Scope<")
    if predicate == "len(name) >= 2":
        return len(materialize(state, "name")) >= 2
    if predicate == "len(name) % 2 == 0":
        return len(materialize(state, "name")) % 2 == 0
    if predicate == 'not name.startswith("qunion")':
        return not materialize(state, "name").startswith("qunion")
    if predicate == 'scope.expression.args.get("by_name") is True':
        scope_repr = state.get("scope")
        if scope_repr is None:
            raise RuntimeError("missing local 'scope' at an observation")
        return "by_name=True" in scope_repr
    raise RuntimeError(f"unknown predicate: {predicate}")


def build_report(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    counts = {predicate: [0, 0] for predicate in PREDICATES}
    state = {}
    target_events = 0
    target_calls = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            target_calls += 1
            state = {}

        state.update(parse_locals(match.group("locals")))
        if event != "line":
            continue

        line = int(match.group("line"))
        candidates = PREDICATES[:5] if line == COMMON_LINE else PREDICATES[5:] if line == ZERO_LINE else ()
        for predicate in candidates:
            counts[predicate][0] += 1
            if not evaluate(predicate, state):
                counts[predicate][1] += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        raise RuntimeError(f"trace contains zero calls for {TARGET_FUNC}")

    return [
        {
            "held_always": observations > 0 and violations == 0,
            "observations": observations,
            "predicate": predicate,
            "violations": violations,
        }
        for predicate, (observations, violations) in sorted(counts.items())
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    try:
        report = build_report(Path(args.trace_log))
    except RuntimeError as exc:
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
    output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    Path(args.out).write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
