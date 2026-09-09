#!/usr/bin/env python3
import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/chat/hf_engine.py"
TARGET_FUNC_SUFFIXES = (".HuggingfaceEngine._process_args", "._process_args")
TARGET_VARIABLES = ["generating_args", "key", "num_return_sequences", "prompt_ids", "system", "value"]

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b.*$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"Trace log not found: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def load_target_function(source_path: Path) -> ast.FunctionDef:
    if not source_path.exists():
        raise SystemExit(f"Target source file not found: {source_path}")
    module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "HuggingfaceEngine":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "_process_args":
                    return child
    raise SystemExit("Could not locate HuggingfaceEngine._process_args in target source file.")


def collect_static_defs_uses(func_node: ast.FunctionDef) -> tuple[dict[str, set[int]], dict[str, set[int]], int, set[str]]:
    tracked = set(TARGET_VARIABLES)
    defs_by_var: dict[str, set[int]] = defaultdict(set)
    uses_by_var: dict[str, set[int]] = defaultdict(set)
    param_names: set[str] = set()

    for arg in list(func_node.args.args) + list(func_node.args.kwonlyargs):
        if arg.arg in tracked:
            defs_by_var[arg.arg].add(func_node.lineno)
            param_names.add(arg.arg)
    if func_node.args.vararg and func_node.args.vararg.arg in tracked:
        defs_by_var[func_node.args.vararg.arg].add(func_node.lineno)
        param_names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg and func_node.args.kwarg.arg in tracked:
        defs_by_var[func_node.args.kwarg.arg].add(func_node.lineno)
        param_names.add(func_node.args.kwarg.arg)

    class DefUseVisitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if node.id in tracked and hasattr(node, "lineno"):
                if isinstance(node.ctx, ast.Load):
                    uses_by_var[node.id].add(node.lineno)
                elif isinstance(node.ctx, ast.Store):
                    defs_by_var[node.id].add(node.lineno)
            self.generic_visit(node)

    DefUseVisitor().visit(func_node)
    return defs_by_var, uses_by_var, func_node.lineno, param_names


def invert_line_map(var_map: dict[str, set[int]]) -> dict[int, set[str]]:
    line_map: dict[int, set[str]] = defaultdict(set)
    for var_name, line_numbers in var_map.items():
        for lineno in line_numbers:
            line_map[lineno].add(var_name)
    return line_map


def collect_invocation_lines(trace_lines: list[str]) -> list[list[int]]:
    matched_events = 0
    call_stack: list[list[int]] = []
    invocations: list[list[int]] = []

    for raw in trace_lines:
        match = TRACE_RE.match(raw)
        if match is None:
            continue
        file_path = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue
        if not any(func_name.endswith(suffix) for suffix in TARGET_FUNC_SUFFIXES):
            continue

        matched_events += 1
        event = match.group("event")
        lineno = int(match.group("lineno"))

        if event == "call":
            call_stack.append([])
            continue
        if event == "line":
            if not call_stack:
                raise SystemExit("Malformed trace: line event without active _process_args call.")
            call_stack[-1].append(lineno)
            continue
        if event in {"return", "exception"}:
            if not call_stack:
                raise SystemExit("Malformed trace: return/exception event without active _process_args call.")
            invocation_lines = call_stack.pop()
            invocations.append(invocation_lines)
            continue

    if matched_events == 0:
        raise SystemExit("Trace contains zero events for target function HuggingfaceEngine._process_args.")
    if call_stack:
        raise SystemExit("Malformed trace: unterminated HuggingfaceEngine._process_args invocation.")
    if not invocations:
        raise SystemExit("Trace contained target events but no completed invocations.")
    if all(len(lines) == 0 for lines in invocations):
        raise SystemExit("All target invocations had zero executed line events.")
    return invocations


def compute_observed_pairs(
    invocations: list[list[int]],
    defs_by_line: dict[int, set[str]],
    uses_by_line: dict[int, set[str]],
    func_def_line: int,
    param_names: set[str],
) -> list[dict[str, int | str]]:
    observed: set[tuple[str, int, int]] = set()

    for executed_lines in invocations:
        current_defs: dict[str, int] = {name: func_def_line for name in param_names}
        for lineno in executed_lines:
            for var_name in uses_by_line.get(lineno, set()):
                def_line = current_defs.get(var_name)
                if def_line is not None:
                    observed.add((var_name, def_line, lineno))
            for var_name in defs_by_line.get(lineno, set()):
                current_defs[var_name] = lineno

    return [
        {"variable": var_name, "def_line": def_line, "use_line": use_line}
        for var_name, def_line, use_line in sorted(observed, key=lambda item: (item[0], item[1], item[2]))
    ]


def main() -> None:
    args = parse_args()
    trace_lines = read_lines(Path(args.trace_log))
    target_source = Path(__file__).resolve().parents[3] / "src/llamafactory/chat/hf_engine.py"
    func_node = load_target_function(target_source)
    defs_by_var, uses_by_var, func_def_line, param_names = collect_static_defs_uses(func_node)
    defs_by_line = invert_line_map(defs_by_var)
    uses_by_line = invert_line_map(uses_by_var)
    invocations = collect_invocation_lines(trace_lines)
    observed_pairs = compute_observed_pairs(invocations, defs_by_line, uses_by_line, func_def_line, param_names)

    if not observed_pairs:
        raise SystemExit("No observed def-use pairs were produced for the tracked variables.")

    oracle = {
        "question_kind": "S4_DataFlow",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/hf_engine_process_args_s4_dataflow__r20260714/files/testcase.py::"
            "TestHuggingfaceEngineProcessArgsDataFlow::test_multibranch_reaching_defs`, "
            "analyze function `src.llamafactory.chat.hf_engine.HuggingfaceEngine._process_args` "
            "in `src/llamafactory/chat/hf_engine.py`. "
            "Track exactly these local variable names: `generating_args`, `key`, `num_return_sequences`, "
            "`prompt_ids`, `system`, and `value`. "
            "A variable definition (def) is any assignment to that local variable, including parameter binding, "
            "where parameters count as defined on the function `def` line. "
            "A variable use is any source line in this function where that variable is read. "
            "Report all unique observed runtime def-use pairs from this test run, where each pair "
            "(`variable`, `def_line`, `use_line`) means the value assigned at `def_line` is later read at "
            "`use_line` before any redefinition of that same variable. "
            "Return JSON with exactly one key `observed_def_use_pairs`, whose value is an array of objects with keys "
            "`variable` (str), `def_line` (int), and `use_line` (int). "
            "Sort ascending by `variable`, then `def_line`, then `use_line`; if any exact duplicate tuples appear, "
            "keep only one."
        ),
        "template_answer": {
            "observed_def_use_pairs": [
                {"variable": "str", "def_line": "int", "use_line": "int"}
            ]
        },
        "oracle_answer": {
            "observed_def_use_pairs": observed_pairs
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], ensure_ascii=True))


if __name__ == "__main__":
    main()
