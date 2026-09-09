#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/model/model_utils/longlora.py"
TARGET_FUNC_NAME = "llama_sdpa_attention_forward"
TARGET_FUNC_SUFFIXES = (f".{TARGET_FUNC_NAME}", TARGET_FUNC_NAME)
TRACKED_VARIABLES = [
    "attention_mask",
    "attn_output",
    "cache_kwargs",
    "causal_mask",
    "cos",
    "groupsz",
    "is_causal",
    "key_states",
    "num_groups",
    "past_key_value",
    "position_embeddings",
    "query_states",
    "sin",
    "value_states",
]

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
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC_NAME:
            return node
    raise SystemExit(f"Could not locate function `{TARGET_FUNC_NAME}` in target source file.")


def collect_static_defs_uses(
    func_node: ast.FunctionDef,
) -> tuple[dict[int, set[str]], dict[int, set[str]], int, set[str]]:
    tracked_set = set(TRACKED_VARIABLES)
    defs_by_line: dict[int, set[str]] = defaultdict(set)
    uses_by_line: dict[int, set[str]] = defaultdict(set)
    parameter_names: set[str] = set()

    for arg in list(func_node.args.posonlyargs) + list(func_node.args.args) + list(func_node.args.kwonlyargs):
        if arg.arg in tracked_set:
            parameter_names.add(arg.arg)
    if func_node.args.vararg and func_node.args.vararg.arg in tracked_set:
        parameter_names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg and func_node.args.kwarg.arg in tracked_set:
        parameter_names.add(func_node.args.kwarg.arg)

    class DefUseVisitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if node.id in tracked_set:
                if isinstance(node.ctx, ast.Load):
                    uses_by_line[node.lineno].add(node.id)
                elif isinstance(node.ctx, (ast.Store, ast.Del)):
                    defs_by_line[node.lineno].add(node.id)
            self.generic_visit(node)

    DefUseVisitor().visit(func_node)
    return defs_by_line, uses_by_line, func_node.lineno, parameter_names


def collect_target_invocations(trace_lines: list[str]) -> list[list[int]]:
    matched_events = 0
    active_stack: list[list[int]] = []
    invocations: list[list[int]] = []

    for raw in trace_lines:
        match = TRACE_RE.match(raw)
        if match is None:
            continue

        file_path = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        event = match.group("event")
        lineno = int(match.group("lineno"))

        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue
        if not any(func_name.endswith(suffix) for suffix in TARGET_FUNC_SUFFIXES):
            continue

        matched_events += 1

        if event == "call":
            active_stack.append([])
            continue
        if event == "line":
            if not active_stack:
                raise SystemExit("Malformed trace: line event without active target call.")
            active_stack[-1].append(lineno)
            continue
        if event in {"return", "exception"}:
            if not active_stack:
                raise SystemExit("Malformed trace: return/exception event without active target call.")
            invocations.append(active_stack.pop())
            continue

    if matched_events == 0:
        raise SystemExit(f"Trace contains zero events for target function `{TARGET_FUNC_NAME}`.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated target invocation(s).")
    if not invocations:
        raise SystemExit("Trace contained target events but no completed invocations.")
    if all(len(lines) == 0 for lines in invocations):
        raise SystemExit("All target invocations had zero executed line events.")
    return invocations


def compute_answer(
    invocations: list[list[int]],
    defs_by_line: dict[int, set[str]],
    uses_by_line: dict[int, set[str]],
    func_def_line: int,
    parameter_names: set[str],
) -> dict[str, object]:
    observed_pairs: set[tuple[int, str, int, int]] = set()
    dead_defs: set[tuple[int, str, int]] = set()
    tracked_sorted = sorted(TRACKED_VARIABLES)

    for invocation_index, executed_lines in enumerate(invocations, start=1):
        current_def: dict[str, int] = {}
        used_by_active_def: dict[tuple[str, int], bool] = {}

        for param in parameter_names:
            current_def[param] = func_def_line
            used_by_active_def[(param, func_def_line)] = False

        for lineno in executed_lines:
            for variable in sorted(uses_by_line.get(lineno, set())):
                def_line = current_def.get(variable)
                if def_line is None:
                    continue
                observed_pairs.add((invocation_index, variable, def_line, lineno))
                used_by_active_def[(variable, def_line)] = True

            for variable in sorted(defs_by_line.get(lineno, set())):
                previous_def = current_def.get(variable)
                if previous_def is not None and not used_by_active_def.get((variable, previous_def), False):
                    dead_defs.add((invocation_index, variable, previous_def))
                current_def[variable] = lineno
                used_by_active_def[(variable, lineno)] = False

        for variable, def_line in current_def.items():
            if not used_by_active_def.get((variable, def_line), False):
                dead_defs.add((invocation_index, variable, def_line))

    observed_items = [
        {
            "invocation_index": invocation_index,
            "variable": variable,
            "def_line": def_line,
            "use_line": use_line,
        }
        for invocation_index, variable, def_line, use_line in sorted(
            observed_pairs, key=lambda x: (x[0], x[1], x[2], x[3])
        )
    ]
    dead_items = [
        {"invocation_index": invocation_index, "variable": variable, "def_line": def_line}
        for invocation_index, variable, def_line in sorted(dead_defs, key=lambda x: (x[0], x[1], x[2]))
    ]

    if not observed_items:
        raise SystemExit("No observed def-use pairs were produced for the tracked variables.")
    if not dead_items:
        raise SystemExit("No dead definitions were produced; scenario is too trivial.")

    return {
        "tracked_variables": tracked_sorted,
        "invocation_def_use_pairs": observed_items,
        "invocation_dead_defs": dead_items,
    }


def build_question() -> str:
    return (
        "For pytest test "
        "`llama_factory_qa/longlora_llama_sdpa_attention_forward_m4_dataflow__r20260714/files/testcase.py::"
        "TestLongLoraSdpaAttentionForwardM4::test_branch_sensitive_dataflow_across_invocations`, "
        "analyze runtime data flow in function "
        "`src.llamafactory.model.model_utils.longlora.llama_sdpa_attention_forward` "
        "from file `src/llamafactory/model/model_utils/longlora.py`. "
        "Track exactly these variables: `attention_mask`, `attn_output`, `cache_kwargs`, `causal_mask`, `cos`, "
        "`groupsz`, `is_causal`, `key_states`, `num_groups`, `past_key_value`, `position_embeddings`, "
        "`query_states`, `sin`, and `value_states`. "
        "A definition (def) is any executed assignment to a tracked variable within this function; parameter bindings "
        "count as definitions on the function `def` line. "
        "A use is any executed read of a tracked variable within this function. "
        "Within one invocation, each use is paired with the most recent earlier definition of the same variable in that "
        "invocation. Invocation indices start at 1 and increment by call order of this function during the test method. "
        "A definition is dead if it is overwritten by another definition of the same variable before any paired use, or if "
        "the invocation returns/raises before any paired use of that definition. "
        "Return JSON with keys: `tracked_variables` (list[str]), `invocation_def_use_pairs` "
        "(list[object with `invocation_index` int, `variable` str, `def_line` int, `use_line` int]), and "
        "`invocation_dead_defs` (list[object with `invocation_index` int, `variable` str, `def_line` int]). "
        "Sort `tracked_variables` lexicographically; sort `invocation_def_use_pairs` by "
        "(`invocation_index`, `variable`, `def_line`, `use_line`); sort `invocation_dead_defs` by "
        "(`invocation_index`, `variable`, `def_line`)."
    )


def main() -> None:
    args = parse_args()
    trace_lines = read_lines(Path(args.trace_log))
    source_path = Path(__file__).resolve().parents[3] / "src/llamafactory/model/model_utils/longlora.py"
    func_node = load_target_function(source_path)
    defs_by_line, uses_by_line, func_def_line, parameter_names = collect_static_defs_uses(func_node)
    invocations = collect_target_invocations(trace_lines)
    oracle_answer = compute_answer(invocations, defs_by_line, uses_by_line, func_def_line, parameter_names)

    payload = {
        "question_kind": "M4_DataFlow",
        "question": build_question(),
        "template_answer": {
            "tracked_variables": ["str"],
            "invocation_def_use_pairs": [
                {"invocation_index": "int", "variable": "str", "def_line": "int", "use_line": "int"}
            ],
            "invocation_dead_defs": [{"invocation_index": "int", "variable": "str", "def_line": "int"}],
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[parser-error] {exc}", file=sys.stderr)
        raise
