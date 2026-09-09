import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "sqlglot/generators/duckdb.py"
TARGET_FUNC = "sqlglot.generators.duckdb.connect_by_to_recursive_cte"
TARGET_NAME = "connect_by_to_recursive_cte"
TRACKED_VARIABLES = (
    "anchor",
    "arg",
    "col",
    "connect",
    "connect_pred",
    "expression",
    "name",
    "outer_query",
    "outer_select_exprs",
    "priors",
    "root",
    "val",
)

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`sqlglot_qa/duckdb_connect_by_to_recursive_cte_s4_dataflow/files/testcase.py::TestDuckDBConnectByDataFlow::test_seeded_recursive_cte_variants`
against this repository. Across all invocations made by that test, what unique
runtime def-use pairs are observed for exactly these local variables:
`anchor`, `arg`, `col`, `connect`, `connect_pred`, `expression`, `name`,
`outer_query`, `outer_select_exprs`, `priors`, `root`, and `val` in
`sqlglot.generators.duckdb.connect_by_to_recursive_cte`, defined in
`sqlglot/generators/duckdb.py`?

A definition ("def") is a parameter binding, assignment target, or successful
`for`-loop target binding in that function's own frame. Parameters count as
defined on the function's `def` line. A use is a read of the named local in
Load context on an executed source statement in that same frame. Attribute or
item mutation does not redefine the local holding the object. For an augmented
assignment such as `total += delta`, treat `total` as a use of its old reaching
definition followed by a new definition on that same line. A `for x in items`
header uses `items` when evaluated and redefines `x` once for each successful
iteration; the final exhausted loop check does not define `x`. Ignore all
definitions and uses syntactically inside list/set/dict comprehensions and
generator expressions, including their iteration variables and iterable
expressions, because those comprehension-local operations are outside the
target function frame.

Within each invocation, a pair is observed when a tracked variable is read and
its current reaching definition is the most recent definition executed before
that read in the invocation. Invocation means one call of the exact target
function, numbered 1-based in chronological order. Analyze every invocation
made by the test, but aggregate their pairs into one set. Include only
operations performed by the target function's own frame; exclude all callee
frames, the nested helper frame, and synthetic comprehension or generator
frames. Call, return, and exception event records do not themselves add defs
or uses. A read in an executed `return` statement is still a use.

Line numbers are absolute 1-based physical lines in
`sqlglot/generators/duckdb.py` as it exists in the repository. Report the line
where the containing simple or compound statement begins. Thus, for a
multi-line assignment, condition, or call, definitions and uses on continued
physical lines are attributed to the first line of that innermost containing
statement. Count that statement's definitions and uses once per execution even
if evaluating its continued lines produces more than one source-line event.
The function's `def` line can appear only as a parameter definition; decorator
and docstring lines do not count as uses or assignment definitions.

Return one JSON object with exactly the key `observed_def_use_pairs`. Its value
must be a list of objects, each with exactly `def_line` (integer), `use_line`
(integer), and `variable` (string). Variable strings use exactly the local
spellings enumerated above; line values are JSON integers, with no string
formatting or null sentinel. Remove duplicate triples, including duplicates
repeated across iterations or invocations, then sort by `variable`
lexicographically ascending, then `def_line` numerically ascending, then
`use_line` numerically ascending."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


class DefUseCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}
        self.statement_lines: list[int] = []
        self._statement_stack: list[ast.stmt] = []

    def visit(self, node):
        if isinstance(node, ast.stmt):
            self._statement_stack.append(node)
            self.statement_lines.append(node.lineno)
            result = super().visit(node)
            self._statement_stack.pop()
            return result
        return super().visit(node)

    def _line(self) -> int:
        return self._statement_stack[-1].lineno

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED_VARIABLES:
            return
        destination = self.uses if isinstance(node.ctx, ast.Load) else self.defs
        destination.setdefault(self._line(), set()).add(node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED_VARIABLES:
            self.uses.setdefault(self._line(), set()).add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return


def analyze_source(source_path: Path):
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        fail(f"cannot parse target source {source_path}: {error}")

    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_NAME
        ),
        None,
    )
    if target is None:
        fail(f"cannot find {TARGET_NAME} in {source_path}")

    collector = DefUseCollector()
    for statement in target.body:
        collector.visit(statement)

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and hasattr(node, "end_lineno")
    ]

    def normalize_line(line: int) -> int:
        enclosing = [
            node for node in statements if node.lineno <= line <= node.end_lineno
        ]
        if not enclosing:
            fail(f"target line event {line} is outside an executable statement")
        return min(
            enclosing,
            key=lambda node: (node.end_lineno - node.lineno, -node.lineno),
        ).lineno

    parameters = {
        argument.arg
        for argument in (
            target.args.posonlyargs + target.args.args + target.args.kwonlyargs
        )
        if argument.arg in TRACKED_VARIABLES
    }
    if target.args.vararg and target.args.vararg.arg in TRACKED_VARIABLES:
        parameters.add(target.args.vararg.arg)
    if target.args.kwarg and target.args.kwarg.arg in TRACKED_VARIABLES:
        parameters.add(target.args.kwarg.arg)

    return target.lineno, parameters, collector.defs, collector.uses, normalize_line


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

    events = []
    source_path = None
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        source_path = Path(match.group("file"))
        events.append((match.group("event"), int(match.group("line"))))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if source_path is None:
        fail("target source path was not present in the trace")

    def_line, parameters, defs, uses, normalize_line = analyze_source(source_path)
    current_defs: dict[str, int] = {}
    pairs: set[tuple[str, int, int]] = set()
    invocation_count = 0
    line_event_count = 0
    previous_statement_line = None

    for event, raw_line in events:
        if event == "call":
            invocation_count += 1
            current_defs = {variable: def_line for variable in parameters}
            previous_statement_line = None
            continue
        if event == "return":
            current_defs = {}
            previous_statement_line = None
            continue
        if event != "line":
            continue

        line_event_count += 1
        line = normalize_line(raw_line)
        if line == previous_statement_line:
            continue
        previous_statement_line = line
        for variable in uses.get(line, ()):
            reaching_definition = current_defs.get(variable)
            if reaching_definition is not None:
                pairs.add((variable, reaching_definition, line))
        for variable in defs.get(line, ()):
            current_defs[variable] = line

    if invocation_count == 0:
        fail(f"trace contains no calls of {TARGET_FUNC}")
    if line_event_count < 40:
        fail(f"target trace is too shallow: only {line_event_count} line events")
    if not pairs:
        fail("no observed def-use pairs were derived from the target trace")

    ordered_pairs = [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": ordered_pairs},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} with {len(ordered_pairs)} unique def-use pairs "
        f"from {invocation_count} invocation(s)."
    )


if __name__ == "__main__":
    main()
