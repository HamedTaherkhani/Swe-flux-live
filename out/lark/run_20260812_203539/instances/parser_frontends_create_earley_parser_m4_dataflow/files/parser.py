import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "lark/parser_frontends.py"
TARGET_FUNC = "lark.parser_frontends.create_earley_parser"
TRACKED = {
    "lexer_conf",
    "parser_conf",
    "options",
    "resolve_ambiguity",
    "debug",
    "tree_class",
    "extra",
    "f",
}

EVENT_RE = re.compile(
    r" (?P<file>/[^ ]+):(?P<line>\d+) "
    r"(?P<func>[^ ]+) event=(?P<event>call|line|return|exception)"
    r"(?: .*?)? locals=(?P<locals>\{.*\})$"
)


def fail(message):
    raise RuntimeError(message)


def load_target_function(source_path):
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(source_path))
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_earley_parser":
            return node
    fail(f"target function not found in {source_path}")


def base_name(target):
    node = target
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def static_flow_model(function):
    uses = {}
    defs = {}

    parameters = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    if function.args.vararg:
        parameters.append(function.args.vararg)
    if function.args.kwarg:
        parameters.append(function.args.kwarg)
    defs[function.lineno] = [arg.arg for arg in parameters if arg.arg in TRACKED]

    for statement in function.body:
        nodes = list(ast.walk(statement))
        for node in nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in TRACKED:
                uses.setdefault(node.lineno, []).append(node.id)

        for assignment in nodes:
            if not isinstance(assignment, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            assignment_defs = []
            targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
            for target in targets:
                if isinstance(target, (ast.Tuple, ast.List)):
                    candidates = list(ast.walk(target))
                else:
                    candidates = [target]
                for candidate in candidates:
                    if isinstance(candidate, ast.Name) and candidate.id in TRACKED:
                        assignment_defs.append(candidate.id)
                    elif isinstance(candidate, (ast.Subscript, ast.Attribute)):
                        name = base_name(candidate)
                        if name in TRACKED:
                            assignment_defs.append(name)
                            break
            defs.setdefault(assignment.lineno, []).extend(assignment_defs)

    return uses, defs


def parse_events(trace_path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw in text.splitlines():
        match = EVENT_RE.search(raw)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse target locals on trace line: {raw!r}: {exc}")
        events.append(
            {
                "line": int(match.group("line")),
                "event": match.group("event"),
                "locals": changed_locals,
            }
        )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def split_invocations(events):
    invocations = []
    current = None
    for event in events:
        if event["event"] == "call":
            if current is not None:
                fail("overlapping target invocations are not supported")
            current = [event]
        elif current is not None:
            current.append(event)
            if event["event"] == "return":
                invocations.append(current)
                current = None
            elif event["event"] == "exception":
                fail("unexpected exception event in target invocation")
    if current is not None:
        fail("unterminated target invocation in trace")
    if not invocations:
        fail("no complete target invocations found")
    return invocations


def compute_pairs(invocations, uses_by_line, defs_by_line, def_line):
    counts = Counter()
    for invocation in invocations:
        reaching = {name: def_line for name in defs_by_line.get(def_line, [])}
        tree_is_none = None
        for event in invocation:
            if event["event"] == "line" and event["line"] == 329:
                value = event["locals"].get("tree_class")
                if value is not None:
                    tree_is_none = value == "None"
        if tree_is_none is None:
            fail("could not determine the conditional path taken on source line 327")

        executed_lines = {
            event["line"] for event in invocation if event["event"] == "line"
        }
        for line in sorted(executed_lines):
            dynamic_uses = list(uses_by_line.get(line, []))
            if line == 327 and tree_is_none:
                try:
                    dynamic_uses.remove("options")
                except ValueError:
                    fail("source model for line 327 did not contain the expected options read")

            for variable in dynamic_uses:
                if variable not in reaching:
                    fail(f"use of {variable!r} on line {line} has no reaching definition")
                counts[(variable, reaching[variable], line)] += 1
            for variable in defs_by_line.get(line, []):
                reaching[variable] = line

    return [
        {
            "count": count,
            "def_line": definition,
            "use_line": use,
            "variable": variable,
        }
        for (variable, definition, use), count in sorted(counts.items())
    ]


def question_text():
    tracked = (
        "debug, extra, f, lexer_conf, options, parser_conf, "
        "resolve_ambiguity, and tree_class"
    )
    return f"""Run every test method whose name starts with `test_` in the unittest class
`TestCreateEarleyParserDataFlow` from
`lark_qa/parser_frontends_create_earley_parser_m4_dataflow/files/testcase.py`.
Use pytest's normal collection order; a target invocation is one chronological
`call` of `lark.parser_frontends.create_earley_parser`, numbered from 1 across
the complete class run. Aggregate the answer over all target invocations made
by all 12 methods in that class.

For `lark.parser_frontends.create_earley_parser` in
`lark/parser_frontends.py`, report all dynamically observed reaching-definition
to use pairs for exactly these tracked local variables: {tracked}.

A definition of a parameter occurs on the function's `def` line. A simple
assignment defines its Name target after the right-hand side has been
evaluated. Reassignments of `f` are separate definitions. For this question,
an item or attribute assignment whose base is a tracked variable both reads
the previous value of that base and then defines the base after the assignment;
thus the mutation of `extra` follows that rule. An augmented assignment would
read its old target value and then define the target, although this function
contains none. A loop target would be defined once per executed iteration
before its body, and a use in a loop would count once per actual evaluation
on each iteration; this function contains no loop. Comprehension-local targets
would be scoped to their comprehension and are excluded unless explicitly
listed above; none are listed.

A use is one actual evaluation of an AST `Name` node in Load context whose
identifier is tracked. Attribute names are not separate Name uses, assignment
Name targets are not uses, and a short-circuited conditional or Boolean operand
is not a use. If two tracked Name reads on one source line both execute, they
are two observations. Each use is paired with the most recent definition of
that variable earlier in the same invocation. One observation means one such
dynamically evaluated use reached by that definition, so repeated executions
add repeated observations.

Line numbers are absolute, 1-based lines in the named repository file.
`def_line` is the line on which the parameter or assignment target begins, and
`use_line` is the line on which the evaluated Name token begins according to
Python's AST source coordinates. For a multi-line statement, this can differ
from the statement's first executed line: each Name is assigned the line where
its own expression begins. The undecorated `def` line can therefore appear as
a parameter definition; decorator and docstring lines do not count.

Return one JSON object with the sole key `observed_def_use_pairs`. Its value is
a list of objects having exactly `count` (JSON integer), `def_line` (JSON
integer), `use_line` (JSON integer), and `variable` (JSON string). `count` is
the total number of observations of that exact triple across all methods and
invocations. Omit triples with zero observations. Emit exactly one row per
unique `(variable, def_line, use_line)` triple; multiplicity appears only in
`count`. Sort rows ascending by `variable`, then `def_line`, then `use_line`,
using ordinary Unicode string order for `variable` and numeric order for
lines. Variable strings are the bare source identifiers shown above (for
example, a hypothetical variable named `cache_item` would be serialized as
`"cache_item"`); no `repr()`, module prefix, null sentinel, or omitted field
is used."""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    function = load_target_function(root / TARGET_FILE)
    uses, definitions = static_flow_model(function)
    events = parse_events(Path(args.trace_log))
    invocations = split_invocations(events)
    pairs = compute_pairs(invocations, uses, definitions, function.lineno)
    if not pairs:
        fail("computed observed_def_use_pairs is empty")

    document = {
        "question_kind": "M4_DataFlow",
        "question": question_text(),
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
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {output} with {len(pairs)} observed def-use pairs")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
