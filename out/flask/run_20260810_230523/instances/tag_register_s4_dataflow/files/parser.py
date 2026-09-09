#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/flask/json/tag.py"
TARGET_FUNC = "flask.json.tag.TaggedJSONSerializer.register"
TRACKED = {"force", "index", "key", "self", "tag", "tag_class"}

QUESTION = """Run the pytest test `flask_qa/tag_register_s4_dataflow/files/testcase.py::TestTaggedJSONSerializerRegister::test_generated_registration_paths` and consider every invocation of `flask.json.tag.TaggedJSONSerializer.register` whose code is in `src/flask/json/tag.py`, including invocations made while constructing the serializer. For the tracked local variables `force`, `index`, `key`, `self`, `tag`, and `tag_class`, report all unique def-use pairs observed at runtime.

A def is a completed assignment to a local name or a parameter binding; all parameters are considered defined at the function's `def` line when each invocation begins. A use is an executed read of that local name in the target function's own frame. Reading `self` as the base of an attribute access counts as a use of `self`; an attribute name itself is not a local-variable use, and a plain assignment target is not a use. A pair `{variable, def_line, use_line}` is observed when the value from that variable's most recent def in the same invocation reaches the stated use without an intervening def. Reaching definitions reset at the start of every invocation.

Treat augmented assignment such as `x += 1` as a use of the old reaching def followed by a new def of `x` on that same line. A `for x in ...` header defines `x` separately on each successful iteration. Comprehension-local target bindings, and reads resolved to those comprehension-local bindings, are excluded; reads in a comprehension that resolve to one of the tracked function-local variables still count.

Line numbers are absolute 1-based source lines in `src/flask/json/tag.py` as it exists in the repository. For a multi-line statement or expression, use the executed line-event line where that statement or expression begins. The function `def` line can appear as a parameter `def_line`; decorator and docstring lines do not count unless they perform a tracked-variable read or def under the rules above.

Take the set union across all invocations and remove duplicate triples. Return exactly `{"observed_def_use_pairs": [...]}`, where every list item has exactly the keys `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort items by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending. There are no additional value-formatting, exception-name, or function-name fields in the answer."""


class DefUseCollector(ast.NodeVisitor):
    def __init__(self):
        self.defs = {}
        self.uses = {}

    def _add(self, table, name, lineno):
        if name in TRACKED:
            table.setdefault(lineno, set()).add(name)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self._add(self.uses, node.id, node.lineno)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._add(self.defs, node.id, node.lineno)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self._add(self.uses, node.target.id, node.lineno)
            self._add(self.defs, node.target.id, node.lineno)
            self.visit(node.value)
        else:
            self.generic_visit(node)


def source_maps(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TaggedJSONSerializer":
            target = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "register"
                ),
                None,
            )
            break
    if target is None:
        raise RuntimeError("target function was not found in source")

    collector = DefUseCollector()
    for statement in target.body:
        collector.visit(statement)

    parameter_names = {
        arg.arg
        for arg in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
        if arg.arg in TRACKED
    }
    if target.args.vararg and target.args.vararg.arg in TRACKED:
        parameter_names.add(target.args.vararg.arg)
    if target.args.kwarg and target.args.kwarg.arg in TRACKED:
        parameter_names.add(target.args.kwarg.arg)
    return target.lineno, parameter_names, collector.defs, collector.uses


def parse_events(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"^(?:\S+ \S+ )?(?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append((match.group("event"), int(match.group("line"))))

    if not events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not any(event == "call" for event, _ in events):
        raise RuntimeError("target trace has no call events")
    return events


def compute_pairs(events, def_line, parameters, definitions, uses):
    pairs = set()
    reaching = {}
    active = False

    for event, lineno in events:
        if event == "call":
            active = True
            reaching = {name: def_line for name in parameters}
            continue
        if not active:
            continue
        if event == "line":
            for name in uses.get(lineno, ()):
                if name in reaching:
                    pairs.add((name, reaching[name], lineno))
            for name in definitions.get(lineno, ()):
                reaching[name] = lineno
        elif event == "return":
            active = False
            reaching = {}

    if not pairs:
        raise RuntimeError("no observed def-use pairs were derived from target events")
    return [
        {"def_line": defn, "use_line": use, "variable": variable}
        for variable, defn, use in sorted(pairs)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    source_path = Path(__file__).resolve().parents[3] / TARGET_FILE
    def_line, parameters, definitions, uses = source_maps(source_path)
    events = parse_events(trace_path)
    observed = compute_pairs(events, def_line, parameters, definitions, uses)

    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
