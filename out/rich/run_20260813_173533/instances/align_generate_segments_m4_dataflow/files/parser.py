#!/usr/bin/env python3
"""Parse trace log for M4_DataFlow observed_def_use_pairs oracle."""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

TARGET_FILE = "rich/align.py"
TARGET_FUNC = "rich.align.Align.__rich_console__.<locals>.generate_segments"
TARGET_FUNC_SUFFIX = "generate_segments"
PARENT_FUNC = "__rich_console__"
TEST_FILE = "rich_qa/align_generate_segments_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestAlignGenerateSegmentsDataFlow"

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

TRACKED_VARIABLES = (
    "align",
    "excess_space",
    "left",
    "line",
    "lines",
    "new_line",
    "pad",
    "pad_right",
    "self",
    "style",
)

# Free-variable reaching defs at generate_segments entry (parent __rich_console__).
ENTRY_LINE = 161

FREE_VAR_ENTRY_DEFS: dict[str, int] = {
    "align": 146,
    "excess_space": 158,
    "lines": 156,
    "new_line": 157,
    "self": 143,
    "style": 159,
}

QUESTION = (
    f"Consider pytest tests in `{TEST_FILE}::{TEST_CLASS}` (every `test_*` "
    "method in that class, executed in pytest's default collection order). "
    "The answer aggregates behavior across the entire pytest run of the class "
    "(all test methods combined, in chronological order).\n\n"
    f"Target function: `{TARGET_FUNC}` in `{TARGET_FILE}` (the nested "
    "generator body spans lines 161-198 as checked into the repository).\n\n"
    "Tracked variables (exact set; no others): "
    + ", ".join(f"`{v}`" for v in TRACKED_VARIABLES)
    + ". These are every local name assigned inside `generate_segments` plus "
    "every cell/free variable referenced from the enclosing `__rich_console__` "
    "frame (`align`, `excess_space`, `lines`, `new_line`, `self`, `style`).\n\n"
    "Definition sites (`def_line`): a 1-based physical source line in "
    f"`{TARGET_FILE}` where a tracked variable receives a new value. "
    "Assignment statements and `for` loop headers (`for line in lines`) define "
    "the loop target on the `for` line. Parameters are defined on their "
    "`def` line; for `self` in the enclosing method that is line 143 "
    "(the `def __rich_console__` line). When `generate_segments` begins, "
    "each free variable's active definition is the assignment in "
    "`__rich_console__` that executed before the nested function was created: "
    "line 146 for `align`, line 156 for `lines` (the second assignment to "
    "`lines`, after `Segment.set_shape`), line 157 for `new_line`, line 158 "
    "for `excess_space`, line 159 for `style`, and line 143 for `self`. "
    "Augmented assignment (`+=`, `*=`, …) performs a use on that line first, "
    "then a definition on the same line. Comprehension iteration variables "
    "are defined on the comprehension line containing the `for` clause; none "
    "appear in this function.\n\n"
    "Use sites (`use_line`): a 1-based physical source line where a tracked "
    "variable appears in a load context (including `if` tests, subscripts, "
    "function arguments, `yield from` operands, and the value read by "
    "augmented assignment before the update). A `for` loop header uses the "
    "iterable variable (`lines`) but does not use the loop target until the "
    "loop body.\n\n"
    "Observation: one use event at `use_line` reached by the definition at "
    "`def_line` counts once. Uses inside a loop body or across repeated "
    "invocations accumulate. Each distinct triple `(variable, def_line, "
    "use_line)` has a total `count` summed over every invocation of "
    "`generate_segments` during the full test run.\n\n"
    "Invocation: one invocation begins at a `call` event whose qualname ends "
    "with `generate_segments` and whose reported line number is 161 (the "
    "`def generate_segments` line). Other `call` events logged at inner lines "
    "during `yield from` delegation are not invocation boundaries. "
    "Invocations are numbered 1-based in chronological order across the full "
    "run. At each invocation entry, reset reaching definitions for locals; "
    "restore free-variable reaching defs to the entry lines listed above. Process "
    "`line` trace events in execution order within each invocation. For each "
    "`line` event, first record all uses on that source line against the "
    "current reaching defs, then apply all definitions on that line (updating "
    "reaching defs). The `line` event is emitted immediately before the "
    "interpreter executes that physical line; uses and defs for the line are "
    "attributed to the line number in the trace.\n\n"
    "Trace scope: only `line` events whose normalized file path equals "
    f"`{TARGET_FILE}` and whose qualname equals `{TARGET_FUNC}`. Ignore "
    "`call`, `return`, and `exception` events for pairing (but `call` marks "
    "invocation boundaries).\n\n"
    "Return JSON with top-level key `observed_def_use_pairs`: a list of "
    "objects each having keys `variable` (str), `def_line` (int), `use_line` "
    "(int), and `count` (int, positive). Include only pairs observed at least "
    "once. Sort the list by `variable` ascending, then `def_line` ascending, "
    "then `use_line` ascending. The triple is unique; multiplicity is carried "
    "only in `count` (no duplicate rows)."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC or func.endswith(f".{TARGET_FUNC_SUFFIX}")


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.find(TARGET_FILE)
    if idx == -1:
        return normalized
    return normalized[idx:]


def _find_nested_function(tree: ast.Module, outer_name: str, inner_name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == outer_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == inner_name:
                    return child
    raise SystemExit(f"Could not locate {inner_name} inside {outer_name}")


def _collect_names(node: ast.AST, ctx_type: type) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ctx_type):
            names.append(child.id)
    return names


def _add_uses(
    uses: dict[int, list[str]], line: int, names: list[str], tracked: set[str]
) -> None:
    for name in names:
        if name in tracked:
            uses[line].append(name)


def _add_defs(
    defs: dict[int, list[str]], line: int, names: list[str], tracked: set[str]
) -> None:
    for name in names:
        if name in tracked:
            defs[line].append(name)


def _analyze_function(func_node: ast.FunctionDef) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    uses: dict[int, list[str]] = defaultdict(list)
    defs: dict[int, list[str]] = defaultdict(list)
    tracked = set(TRACKED_VARIABLES)
    for stmt in func_node.body:
        _process_stmt(stmt, uses, defs, tracked)
    return uses, defs


def _process_stmt(
    stmt: ast.AST,
    uses: dict[int, list[str]],
    defs: dict[int, list[str]],
    tracked: set[str],
) -> None:
    if isinstance(stmt, ast.If):
        _add_uses(uses, stmt.test.lineno, _collect_names(stmt.test, ast.Load), tracked)
        for inner in stmt.body:
            _process_stmt(inner, uses, defs, tracked)
        for inner in stmt.orelse:
            _process_stmt(inner, uses, defs, tracked)
        return

    if isinstance(stmt, ast.For):
        line = stmt.lineno
        _add_uses(uses, line, _collect_names(stmt.iter, ast.Load), tracked)
        _add_defs(defs, line, _collect_names(stmt.target, ast.Store), tracked)
        for inner in stmt.body:
            _process_stmt(inner, uses, defs, tracked)
        for inner in stmt.orelse:
            _process_stmt(inner, uses, defs, tracked)
        return

    if isinstance(stmt, ast.Assign):
        line = stmt.lineno
        _add_uses(uses, line, _collect_names(stmt.value, ast.Load), tracked)
        for target in stmt.targets:
            _add_defs(defs, line, _collect_names(target, ast.Store), tracked)
        return

    if isinstance(stmt, ast.AnnAssign):
        line = stmt.lineno
        if stmt.value is not None:
            _add_uses(uses, line, _collect_names(stmt.value, ast.Load), tracked)
        if stmt.target is not None:
            _add_defs(defs, line, _collect_names(stmt.target, ast.Store), tracked)
        return

    if isinstance(stmt, ast.AugAssign):
        line = stmt.lineno
        _add_uses(uses, line, _collect_names(stmt.target, ast.Load), tracked)
        _add_uses(uses, line, _collect_names(stmt.value, ast.Load), tracked)
        _add_defs(defs, line, _collect_names(stmt.target, ast.Store), tracked)
        return

    if isinstance(stmt, ast.Expr):
        _add_uses(uses, stmt.lineno, _collect_names(stmt.value, ast.Load), tracked)
        return

    if isinstance(stmt, ast.Return) and stmt.value is not None:
        _add_uses(uses, stmt.lineno, _collect_names(stmt.value, ast.Load), tracked)
        return

    if isinstance(stmt, ast.With):
        for item in stmt.items:
            if item.context_expr is not None:
                _add_uses(
                    uses,
                    item.context_expr.lineno,
                    _collect_names(item.context_expr, ast.Load),
                    tracked,
                )
        for inner in stmt.body:
            _process_stmt(inner, uses, defs, tracked)
        return


def _parse_trace(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log empty: {path}")

    events: list[dict] = []
    for raw in text.splitlines():
        m = TRACE_RE.match(raw)
        if not m:
            continue
        file_path = _normalize_file(m.group("file"))
        if file_path != TARGET_FILE:
            continue
        func = m.group("func")
        if not _func_matches(func):
            continue
        events.append(
            {
                "lineno": int(m.group("lineno")),
                "func": func,
                "event": m.group("event"),
            }
        )
    return events


def _observed_pairs(
    events: list[dict],
    line_uses: dict[int, list[str]],
    line_defs: dict[int, list[str]],
) -> list[dict]:
    pair_counts: dict[tuple[str, int, int], int] = defaultdict(int)
    current_defs: dict[str, int] = {}
    line_events = 0
    in_invocation = False

    for ev in events:
        if ev["event"] == "call":
            if ev["lineno"] != ENTRY_LINE:
                continue
            current_defs = dict(FREE_VAR_ENTRY_DEFS)
            in_invocation = True
            continue
        if ev["event"] != "line":
            continue
        if not in_invocation:
            continue
        line_events += 1
        lineno = ev["lineno"]
        for var in line_uses.get(lineno, []):
            def_line = current_defs.get(var)
            if def_line is None:
                continue
            pair_counts[(var, def_line, lineno)] += 1
        for var in line_defs.get(lineno, []):
            current_defs[var] = lineno

    if line_events == 0:
        raise SystemExit(f"No line events for {TARGET_FUNC} in trace log")

    pairs = [
        {
            "variable": var,
            "def_line": def_line,
            "use_line": use_line,
            "count": count,
        }
        for (var, def_line, use_line), count in sorted(pair_counts.items())
    ]
    if not pairs:
        raise SystemExit("No def-use pairs observed")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default="/testbed")
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    source = (repo_root / TARGET_FILE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func_node = _find_nested_function(tree, PARENT_FUNC, "generate_segments")
    line_uses, line_defs = _analyze_function(func_node)

    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    pairs = _observed_pairs(events, line_uses, line_defs)
    oracle_answer = {"observed_def_use_pairs": pairs}
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
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
