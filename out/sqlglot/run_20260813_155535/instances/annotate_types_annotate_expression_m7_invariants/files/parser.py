import argparse
import ast
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.optimizer.annotate_types.TypeAnnotator._annotate_expression"
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/annotate_types\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* locals=(?P<locals>\{.*\})$"
)

PREDICATES = {
    "'Column(' occurs in repr(expr)": 464,
    "'NeverSeen' occurs in repr(expr)": 505,
    "'metric_' occurs in repr(expr)": 499,
    "children_annotated is True": 464,
    "identifier.this == 'NeverSeen'": 529,
}

QUESTION = (
    "Run every pytest test method whose name begins `test_` in "
    "`sqlglot_qa/annotate_types_annotate_expression_m7_invariants/files/testcase.py::"
    "TestAnnotateExpressionInvariants`; the answer aggregates observations from ALL such "
    "methods in that class, so all 12 collected test methods contribute. A method is "
    "identified by its full pytest id "
    "`sqlglot_qa/annotate_types_annotate_expression_m7_invariants/files/testcase.py::"
    "TestAnnotateExpressionInvariants::<method_name>`, and methods execute in pytest's "
    "default collection order. During the complete run, consider Python executions of "
    "exactly `sqlglot.optimizer.annotate_types.TypeAnnotator._annotate_expression` in "
    "`sqlglot/optimizer/annotate_types.py`; calls of other functions, including callees, "
    "do not count. An invocation is one Python `call` of exactly that function, numbered "
    "1-based in chronological call order across all covered methods. Evaluate the following "
    "five candidate predicates verbatim at their specified observation points: "
    "(1) `'Column(' occurs in repr(expr)` at every `line` event for line 464; "
    "(2) `'NeverSeen' occurs in repr(expr)` at every `line` event for line 505; "
    "(3) `'metric_' occurs in repr(expr)` at every `line` event for line 499; "
    "(4) `children_annotated is True` at every `line` event for line 464; and "
    "(5) `identifier.this == 'NeverSeen'` at every `line` event for line 529. "
    "Each observation uses the target invocation's live local values immediately before "
    "the statement beginning on that line executes. `repr(x)` means Python's standard "
    "`repr()` of the whole current object, and `occurs` means a case-sensitive substring "
    "test with no normalization. The other predicates use Python identity/equality semantics "
    "exactly as written. Line numbers are absolute, 1-based lines in the named repository "
    "file. For a multi-line statement or expression, its line event belongs to the line on "
    "which that statement or expression begins; decorator and docstring lines are not "
    "observations, and the function's `def` line is not an observation unless Python emits "
    "the specifically named line event. Count every qualifying event, including repeated "
    "events in one invocation; do not deduplicate. For each predicate, `observations` is its "
    "total number of evaluations across all methods, `violations` is the number that evaluate "
    "to false, and `held_always` is exactly `violations == 0` when observations are positive. "
    "A predicate whose observation point is never reached must instead be reported as "
    "`observations: 0`, `violations: 0`, and `held_always: false`. Return exactly a JSON object "
    "with key `invariant_report`, whose value is a list containing one object per candidate "
    "with exactly these keys and types: `held_always` (JSON boolean), `observations` "
    "(integer), `predicate` (string copied verbatim from the candidate), and `violations` "
    "(integer). Sort entries by the `predicate` string ascending using Unicode code-point "
    "order. Candidate strings are unique; if equal strings were present, break ties by "
    "observation line ascending and then by their order above. Preserve duplicate "
    "observations, emit no extra keys, and use JSON spelling (`true`/`false`, not Python "
    "`True`/`False`); no null, empty-string, exception-name, or function-name values occur "
    "in the answer."
)


def parse_locals(raw: str) -> dict[str, str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(f"could not parse traced locals: {raw}") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise RuntimeError(f"unexpected traced locals payload: {raw}")
    return value


def evaluate(predicate: str, state: dict[str, str]) -> bool:
    if predicate == "'Column(' occurs in repr(expr)":
        return "Column(" in require_local(state, "expr")
    if predicate == "'NeverSeen' occurs in repr(expr)":
        return "NeverSeen" in require_local(state, "expr")
    if predicate == "'metric_' occurs in repr(expr)":
        return "metric_" in require_local(state, "expr")
    if predicate == "children_annotated is True":
        return require_local(state, "children_annotated") == "True"
    if predicate == "identifier.this == 'NeverSeen'":
        identifier = require_local(state, "identifier")
        return bool(re.search(r"(?:this=)?'NeverSeen'", identifier))
    raise RuntimeError(f"unknown predicate: {predicate}")


def require_local(state: dict[str, str], name: str) -> str:
    if name not in state:
        raise RuntimeError(f"required local {name!r} is unavailable at observation")
    return state[name]


def compute_report(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    counts = {
        predicate: {"observations": 0, "violations": 0} for predicate in PREDICATES
    }
    active_states: list[dict[str, str]] = []
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        changed = parse_locals(match.group("locals"))

        if event == "call":
            active_states.append(dict(changed))
            continue
        if not active_states:
            raise RuntimeError(f"target {event} event occurred outside an active invocation")

        state = active_states[-1]
        state.update(changed)
        if event == "line":
            for predicate, observation_line in PREDICATES.items():
                if line == observation_line:
                    result = evaluate(predicate, state)
                    counts[predicate]["observations"] += 1
                    if not result:
                        counts[predicate]["violations"] += 1
        elif event == "return":
            active_states.pop()

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_states:
        raise RuntimeError("one or more target invocations did not complete")

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
    return report


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
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
        "oracle_answer": {"invariant_report": compute_report(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
