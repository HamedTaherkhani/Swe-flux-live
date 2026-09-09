import ast
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/qualify_columns.py"
TARGET_FUNC = "sqlglot.optimizer.qualify_columns._expand_stars"
INVOCATION = 3

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`sqlglot_qa/qualify_columns_expand_stars_s1_cfg/files/testcase.py::TestExpandStarsControlFlow::test_nested_star_modifiers_and_using_join`
against this repository. What is the exact ordered sequence of executed source-line
events in the third invocation of
`sqlglot.optimizer.qualify_columns._expand_stars`, defined in
`sqlglot/optimizer/qualify_columns.py`?

Count invocations 1-based in chronological order: an invocation begins with a
`call` event for that exact function, so the requested invocation is the third
such call during the test. Include only `line` events emitted by that invocation's
own function frame. Exclude its `call`, `return`, and `exception` events, all
callee frames, and synthetic frames for comprehensions or generator expressions.

Return one JSON object with exactly the key `executed_path`, whose value is a
list of objects. Every list object must have exactly these keys and types:
`file` (string), `func` (string), and `line` (integer). Set `file` to the
repo-relative POSIX path `sqlglot/optimizer/qualify_columns.py` and `func` to
the fully dotted name `sqlglot.optimizer.qualify_columns._expand_stars` in
every element. `line` is the absolute 1-based physical line number in that
file as it exists in the repository. For example, a function `pkg.mod.work`
in `pkg/mod.py` would use those exact two strings.

Preserve chronological event order and retain every repeated line event; do
not sort or deduplicate the list. The function's `def` line, decorator lines,
and docstring line are not line events in this sequence. The function contains
multi-line calls and conditions. If a line event is attributed to a visually
continued line of a multi-line statement, report the `lineno` of the innermost
enclosing Python AST statement instead; thus every event for one multi-line
statement uses the physical line where that statement begins."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def statement_start_lines(source_path: Path, lines: list[int]) -> list[int]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        fail(f"cannot parse target source {source_path}: {error}")

    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_expand_stars"
        ),
        None,
    )
    if target is None:
        fail(f"cannot find _expand_stars in target source {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt) and node is not target and hasattr(node, "end_lineno")
    ]
    normalized = []
    for line in lines:
        enclosing = [
            node
            for node in statements
            if node.lineno <= line <= node.end_lineno
        ]
        if not enclosing:
            fail(f"line event {line} is outside an executable statement")
        statement = min(
            enclosing,
            key=lambda node: (node.end_lineno - node.lineno, -node.lineno),
        )
        normalized.append(statement.lineno)
    return normalized


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    invocation_count = 0
    active_invocation = None
    target_event_count = 0
    executed_lines = []
    source_path = None

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        source_path = Path(match.group("file"))
        target_event_count += 1
        event = match.group("event")
        if event == "call":
            invocation_count += 1
            active_invocation = invocation_count
        elif event == "line" and active_invocation == INVOCATION:
            executed_lines.append(int(match.group("line")))
        elif event == "return":
            active_invocation = None

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < INVOCATION:
        fail(
            f"trace contains only {invocation_count} invocation(s) of {TARGET_FUNC}; "
            f"invocation {INVOCATION} is required"
        )
    if not executed_lines:
        fail(f"invocation {INVOCATION} contains no line events")
    if source_path is None:
        fail("target source path was not present in the trace")

    executed_lines = statement_start_lines(source_path, executed_lines)
    if len(executed_lines) < 50 or len(set(executed_lines)) < 12:
        fail(
            f"invocation {INVOCATION} is too shallow: {len(executed_lines)} line "
            f"events across {len(set(executed_lines))} distinct lines"
        )

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
                for line in executed_lines
            ]
        },
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} with {len(executed_lines)} ordered line events "
        f"from invocation {INVOCATION}."
    )


if __name__ == "__main__":
    main()
