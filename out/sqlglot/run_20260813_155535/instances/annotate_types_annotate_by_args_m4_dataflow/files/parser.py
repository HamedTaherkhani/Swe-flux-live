import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re


TARGET_FILE = "sqlglot/optimizer/annotate_types.py"
TARGET_FUNC = "sqlglot.optimizer.annotate_types.TypeAnnotator._annotate_by_args"
TRACKED = {
    "arg",
    "args",
    "array",
    "expr",
    "expression",
    "expressions",
    "expr_type",
    "literal_this_type",
    "literal_type",
    "nested_type",
    "non_literal_this_type",
    "non_literal_type",
    "promote",
    "result_type",
    "self",
    "this_type",
}
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/annotate_types\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run every pytest test method whose name begins `test_` in "
    "`sqlglot_qa/annotate_types_annotate_by_args_m4_dataflow/files/testcase.py::"
    "TestAnnotateByArgsDataFlow`. The answer aggregates observations across ALL 12 such "
    "methods in the class. Identify a method by the full pytest id "
    "`sqlglot_qa/annotate_types_annotate_by_args_m4_dataflow/files/testcase.py::"
    "TestAnnotateByArgsDataFlow::<method_name>`; use pytest's default collection order. "
    "Consider only invocations of exactly "
    "`sqlglot.optimizer.annotate_types.TypeAnnotator._annotate_by_args` in "
    "`sqlglot/optimizer/annotate_types.py`; activity in callers and callees is excluded. "
    "An invocation is one Python call of exactly that function, numbered 1-based in "
    "chronological order over the complete class run. Compute dynamic reaching-definition "
    "observations for exactly these tracked local variables, with source spelling and no "
    "others: `arg`, `args`, `array`, `expr`, `expression`, `expressions`, `expr_type`, "
    "`literal_this_type`, `literal_type`, `nested_type`, `non_literal_this_type`, "
    "`non_literal_type`, `promote`, `result_type`, `self`, and `this_type`. Parameters, "
    "including `*args` and keyword-only parameters, are definitions at the function's `def` "
    "line for each invocation. A plain assignment defines each bare-name target on the "
    "1-based line where its assignment statement begins, and that definition starts reaching "
    "uses after the statement completes. A `for` target is defined on the loop-header line "
    "only for a successful iteration, immediately before the first body statement; the "
    "exhaustion check creates no definition. Thus iteration N means the Nth successful "
    "execution of that loop's body, and a later iteration's loop-target definition kills the "
    "earlier one. Any other executed definition of the same tracked variable likewise kills "
    "the previous reaching definition. An augmented assignment is one use of its target "
    "under the use rule below followed by a definition on the augmented-assignment statement "
    "line. A comprehension induction variable follows the same successful-iteration rule "
    "inside its comprehension scope; comprehension-local names would be excluded unless "
    "listed above (this target has none). "
    "A use is a load-context `ast.Name` occurrence of a tracked variable in the target "
    "function. Its `use_line` is that AST occurrence's absolute, 1-based line in the named "
    "repository file. Observe a use once each time Python reaches a line-execution event for "
    "that exact line in the target frame, paired with the definition reaching immediately "
    "before the line executes. If a source line contains multiple load-context occurrences "
    "of the same name, each occurrence is a separate observation. This is deliberately a "
    "line-level definition: every syntactic load occurrence on a reached line counts even if "
    "short-circuit evaluation on that line would skip its bytecode load. Repeated loop-body "
    "line executions count separately, so a use in a loop counts once per reached iteration "
    "per syntactic occurrence. For multiline code, a plain assignment's `def_line` is where "
    "the assignment statement begins, while a use belongs to the line where its particular "
    "name expression begins as reported by Python's AST; Python line events on continuation "
    "expression lines therefore count for those lines. Decorator and docstring lines do not "
    "count, and call/return/exception events are not use observations. "
    "For every observed triple, `count` is the total number of those use observations summed "
    "across all invocations in all test methods. Omit triples with zero observations. Return "
    "exactly one JSON object with key `observed_def_use_pairs`; its value is a list of objects "
    "having exactly `count` (integer), `def_line` (integer), `use_line` (integer), and "
    "`variable` (string). Line integers use ordinary decimal JSON numbers. Variable strings "
    "are copied exactly from the tracked spelling above; no `repr`, module prefix, null, or "
    "empty-string convention applies. Sort rows by (`variable`, `def_line`, `use_line`) "
    "ascending, comparing variable strings by Unicode code-point order and integers "
    "numerically. Emit one unique row per triple: do not duplicate rows, because `count` "
    "carries all multiplicity."
)


def target_node(source_path: Path) -> ast.FunctionDef:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_annotate_by_args":
            return node
    raise RuntimeError(f"target function is missing from {source_path}")


def bare_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name) and node.id in TRACKED:
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(bare_targets(item) for item in node.elts))
    return set()


def static_flow(source_path: Path):
    function = target_node(source_path)
    parameters = {
        argument.arg
        for argument in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
            + ([function.args.vararg] if function.args.vararg else [])
            + ([function.args.kwarg] if function.args.kwarg else [])
        )
        if argument.arg in TRACKED
    }
    uses: dict[int, Counter[str]] = {}
    assignments: dict[int, tuple[int, set[str]]] = {}
    loops: dict[int, tuple[int, set[str]]] = {}

    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in TRACKED:
            uses.setdefault(node.lineno, Counter())[node.id] += 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = set().union(*(bare_targets(target) for target in targets))
            if names:
                assignments[node.lineno] = (node.end_lineno or node.lineno, names)
        elif isinstance(node, ast.AugAssign):
            names = bare_targets(node.target)
            if names:
                assignments[node.lineno] = (node.end_lineno or node.lineno, names)
                uses.setdefault(node.lineno, Counter()).update(names)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names = bare_targets(node.target)
            if names:
                loops[node.lineno] = (node.body[0].lineno, names)

    found = parameters | set().union(
        *(names for _, names in assignments.values()),
        *(names for _, names in loops.values()),
    )
    if found != TRACKED:
        raise RuntimeError(
            f"tracked-variable mismatch: expected {sorted(TRACKED)}, found {sorted(found)}"
        )
    return function.lineno, parameters, uses, assignments, loops


def compute_pairs(trace_path: Path, source_path: Path) -> list[dict[str, object]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    def_line, parameters, uses, assignments, loops = static_flow(source_path)
    counts: Counter[tuple[str, int, int]] = Counter()
    active: list[dict[str, object]] = []
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            active.append(
                {
                    "definitions": {name: def_line for name in parameters},
                    "pending": [],
                    "previous_line": None,
                }
            )
            continue
        if not active:
            raise RuntimeError(f"target {event} event occurred outside an active invocation")

        state = active[-1]
        definitions = state["definitions"]
        pending = state["pending"]
        previous_line = state["previous_line"]

        if event == "line":
            still_pending = []
            for start, end, names in pending:
                if start <= line <= end:
                    still_pending.append((start, end, names))
                else:
                    for name in names:
                        definitions[name] = start
            state["pending"] = still_pending

            if previous_line in loops and line == loops[previous_line][0]:
                for name in loops[previous_line][1]:
                    definitions[name] = previous_line

            for variable, multiplicity in uses.get(line, {}).items():
                reaching = definitions.get(variable)
                if reaching is None:
                    raise RuntimeError(
                        f"use of {variable!r} on line {line} has no reaching definition"
                    )
                counts[(variable, reaching, line)] += multiplicity

            if line in assignments:
                end, names = assignments[line]
                state["pending"].append((line, end, names))
            state["previous_line"] = line
        elif event == "return":
            active.pop()

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active:
        raise RuntimeError("one or more target invocations did not complete")
    if not counts:
        raise RuntimeError("target trace produced zero def-use observations")

    return [
        {
            "count": count,
            "def_line": def_line,
            "use_line": use_line,
            "variable": variable,
        }
        for (variable, def_line, use_line), count in sorted(counts.items())
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()
    source_path = Path(__file__).resolve().parents[3] / TARGET_FILE

    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "count": "int",
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ]
        },
        "oracle_answer": {
            "observed_def_use_pairs": compute_pairs(args.trace_log, source_path)
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
