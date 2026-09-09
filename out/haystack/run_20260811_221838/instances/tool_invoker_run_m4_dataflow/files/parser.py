import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = Path("haystack/components/tools/tool_invoker.py")
TARGET_FUNC = "haystack.components.tools.tool_invoker.run"
TRACKED = (
    "callable_",
    "e",
    "enable_streaming_callback_passthrough",
    "error_chat_message",
    "error_message",
    "error_messages",
    "executor",
    "future",
    "futures",
    "messages_with_tool_calls",
    "params",
    "resolved_enable_streaming_passthrough",
    "result",
    "state",
    "streaming_callback",
    "tool_call",
    "tool_call_params",
    "tool_calls",
    "tool_messages",
    "tool_to_invoke",
    "tools",
    "tools_with_names",
)

QUESTION = """Execute every pytest test method in `haystack_qa/tool_invoker_run_m4_dataflow/files/testcase.py::TestToolInvokerRunDataFlow` (that is, every method whose name starts with `test_` in that class). Pytest IDs have the form `haystack_qa/tool_invoker_run_m4_dataflow/files/testcase.py::TestToolInvokerRunDataFlow::<method_name>`. Aggregate over all those methods and report the runtime-observed def-use pairs, with observation counts, for `haystack.components.tools.tool_invoker.ToolInvoker.run` in `haystack/components/tools/tool_invoker.py`.

Track exactly these target-frame variables: `callable_`, `e`, `enable_streaming_callback_passthrough`, `error_chat_message`, `error_message`, `error_messages`, `executor`, `future`, `futures`, `messages_with_tool_calls`, `params`, `resolved_enable_streaming_passthrough`, `result`, `state`, `streaming_callback`, `tool_call`, `tool_call_params`, `tool_calls`, `tool_messages`, `tool_to_invoke`, `tools`, and `tools_with_names`.

A definition (“def”) is a binding of a tracked name by an assignment target, a `for` target, a `with ... as` target, an exception-handler `as` target, or a parameter binding, when that construct executes in the target function's own frame. Mutating an object through a method call or attribute/subscript store does not redefine the variable holding that object. Parameters are defined on the function's `def` line on every invocation. On an ordinary assignment, evaluate and count reads before applying that line's definitions. An augmented assignment such as `x += 1` reads the old reaching definition and then defines `x` on the same line, so it is both a use and a def.

A use observation is defined operationally from Python target-frame line events and source AST loads: whenever a line event occurs, count once every syntactic `ast.Name` load of a tracked name whose load node begins on that line. If the line contains two separate load nodes for the same name, count two observations. If Python emits that line event again while resuming a multi-line call expression after a callee returns, count the line's loads again; this event-based rule applies even when a same-line subexpression would be skipped by short-circuit evaluation. On each ordinary line event, count uses first and then apply every tracked definition whose target begins on that line. A pair is observed when the most recently applied definition of that variable reaches that use event with no intervening applied definition. A `for x in expression` is the one special case to the ordinary line-event rule: count tracked loads in `expression` only once when that loop is entered, and each successful iteration defines `x` on the loop-header line before the body; the final unsuccessful iterator check defines nothing and does not recount the iterable expression. Thus, iteration N is the Nth successful binding of the loop target, equivalently the Nth entry into that loop body. Comprehension-local bindings and all events in implicit comprehension frames are excluded. Callers, callees, worker-thread tool frames, and nested implicit frames are excluded even if they read a name with the same spelling. Call and return events delimit invocations but do not themselves create use observations; exception events are ignored, while a subsequently executed exception-handler line follows the ordinary definition rule.

An invocation is one `call` of the exact target function, numbered 1-based in chronological order across pytest's normal collection/execution order. Counts are totals across all invocations in all test methods in the class. `count` is the number of individual use observations for one exact `(variable, def_line, use_line)` triple; a use in a loop body therefore contributes once per iteration in which it executes. Omit triples that are never observed. Emit each triple exactly once: multiplicity is carried only by `count`, so there are no duplicate rows.

Line numbers are absolute 1-based line numbers in the named repository file as it exists for the run. For a multi-line statement or expression, a tracked target or load is assigned the line on which that specific AST target or load expression begins, not necessarily the first line of the enclosing statement. The function's `def` line may appear for parameter definitions. Decorator and docstring lines do not count unless they contain an executed tracked binding or load in the target frame.

Return a JSON object with exactly one key, `observed_def_use_pairs`, mapped to a list of objects. Each object has exactly `count` (JSON integer), `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort rows by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending. The triple is unique; `count` is not a sorting or deduplication key. Variable strings are the source identifiers exactly as written. No `repr()` or `str()` formatting is involved, and JSON null or an empty-string sentinel is never used because every emitted field is a string identifier or integer."""


def _bound_names(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
    return names


class _LoadCollector(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.by_line = {}

    def visit_Name(self, node):
        if node.id in self.tracked and isinstance(node.ctx, ast.Load):
            self.by_line.setdefault(node.lineno, Counter())[node.id] += 1

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        return

    def visit_SetComp(self, node):
        return

    def visit_DictComp(self, node):
        return

    def visit_GeneratorExp(self, node):
        return


class _FunctionFacts(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.defs_by_line = {}
        self.uses_by_line = {}
        self.loops = {}

    def _add_def(self, line, variable):
        if variable in self.tracked:
            self.defs_by_line.setdefault(line, set()).add(variable)

    def _merge_loads(self, destination, collected):
        for line, counts in collected.items():
            destination.setdefault(line, Counter()).update(counts)

    def visit_Name(self, node):
        if node.id not in self.tracked:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses_by_line.setdefault(node.lineno, Counter())[node.id] += 1
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._add_def(node.lineno, node.id)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name) and node.target.id in self.tracked:
            self.uses_by_line.setdefault(node.target.lineno, Counter())[node.target.id] += 1
            self._add_def(node.target.lineno, node.target.id)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_ExceptHandler(self, node):
        if node.name:
            self._add_def(node.lineno, node.name)
        for statement in node.body:
            self.visit(statement)

    def _visit_loop(self, node):
        collector = _LoadCollector(self.tracked)
        collector.visit(node.iter)
        body_start = min(statement.lineno for statement in node.body)
        body_end = max(getattr(statement, "end_lineno", statement.lineno) for statement in node.body)
        self.loops[node.lineno] = {
            "iter_uses": collector.by_line,
            "targets": sorted(_bound_names(node.target) & self.tracked),
            "body_start": body_start,
            "body_end": body_end,
        }
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_For(self, node):
        self._visit_loop(node)

    def visit_AsyncFor(self, node):
        self._visit_loop(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        return

    def visit_SetComp(self, node):
        return

    def visit_DictComp(self, node):
        return

    def visit_GeneratorExp(self, node):
        return


def source_facts(source_path):
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot inspect target source {source_path}: {exc}") from exc

    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ToolInvoker":
            target = next(
                (member for member in node.body if isinstance(member, ast.FunctionDef) and member.name == "run"),
                None,
            )
            break
    if target is None:
        raise RuntimeError("could not locate ToolInvoker.run in target source")

    facts = _FunctionFacts(TRACKED)
    for statement in target.body:
        facts.visit(statement)

    parameter_defs = {}
    arguments = (*target.args.posonlyargs, *target.args.args, *target.args.kwonlyargs)
    for argument in arguments:
        if argument.arg in TRACKED:
            parameter_defs[argument.arg] = target.lineno
    if target.args.vararg and target.args.vararg.arg in TRACKED:
        parameter_defs[target.args.vararg.arg] = target.lineno
    if target.args.kwarg and target.args.kwarg.arg in TRACKED:
        parameter_defs[target.args.kwarg.arg] = target.lineno
    return facts, parameter_defs


def _record_uses(counts, active_defs, uses, line_number):
    for variable, multiplicity in sorted(uses.items()):
        if variable not in active_defs:
            raise RuntimeError(f"executed use of {variable!r} at line {line_number} has no reaching definition")
        counts[(variable, active_defs[variable], line_number)] += multiplicity


def _process_invocation(line_events, facts, parameter_defs, counts):
    active_defs = dict(parameter_defs)
    entered_loops = set()
    for index, line_number in enumerate(line_events):
        loop = facts.loops.get(line_number)
        if loop is not None:
            if line_number not in entered_loops:
                for use_line, uses in sorted(loop["iter_uses"].items()):
                    _record_uses(counts, active_defs, uses, use_line)
                entered_loops.add(line_number)
            next_line = line_events[index + 1] if index + 1 < len(line_events) else None
            successful_iteration = (
                next_line is not None and loop["body_start"] <= next_line <= loop["body_end"]
            )
            if successful_iteration:
                for variable in loop["targets"]:
                    active_defs[variable] = line_number
            continue

        _record_uses(counts, active_defs, facts.uses_by_line.get(line_number, {}), line_number)
        for variable in sorted(facts.defs_by_line.get(line_number, ())):
            active_defs[variable] = line_number


def observed_pairs(trace_path, facts, parameter_defs):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"(?P<path>\S*haystack/components/tools/tool_invoker\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    target_events = 0
    active_lines = None
    complete_invocations = 0
    counts = Counter()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            if active_lines is not None:
                raise RuntimeError("overlapping target invocations found in trace")
            active_lines = []
        elif event == "line":
            if active_lines is None:
                raise RuntimeError("target line event found outside an invocation")
            active_lines.append(line_number)
        elif event == "return":
            if active_lines is None:
                raise RuntimeError("target return event found without a matching call")
            _process_invocation(active_lines, facts, parameter_defs, counts)
            active_lines = None
            complete_invocations += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_lines is not None:
        raise RuntimeError("trace ended during an active target invocation")
    if complete_invocations == 0:
        raise RuntimeError(f"trace contains no complete invocations of {TARGET_FUNC}")
    if not counts:
        raise RuntimeError("no observed def-use pairs were computed")

    return [
        {"variable": variable, "def_line": def_line, "use_line": use_line, "count": count}
        for (variable, def_line, use_line), count in sorted(
            counts.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        )
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        facts, parameter_defs = source_facts(TARGET_FILE)
        pairs = observed_pairs(args.trace_log, facts, parameter_defs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
