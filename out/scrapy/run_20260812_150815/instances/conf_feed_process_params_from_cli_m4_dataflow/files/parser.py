from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "scrapy/utils/conf.py"
TARGET_FUNC = "scrapy.utils.conf.feed_process_params_from_cli"
TRACKED_VARIABLES = (
    "element",
    "feed_format",
    "feed_uri",
    "output",
    "overwrite",
    "overwrite_output",
    "result",
    "settings",
    "valid_output_formats",
)
TRACKED_SET = set(TRACKED_VARIABLES)

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


class FunctionAccessCollector(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef):
        self.root = root
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}
        self.for_iter_uses: dict[int, set[str]] = {}

    @staticmethod
    def _add(table: dict[int, set[str]], line: int, name: str) -> None:
        table.setdefault(line, set()).add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is not self.root:
            return
        for statement in node.body:
            self.visit(statement)

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

    def visit_For(self, node: ast.For) -> None:
        for child in ast.walk(node.iter):
            if (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id in TRACKED_SET
            ):
                self._add(self.for_iter_uses, child.lineno, child.id)
        self.visit(node.target)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED_SET:
            return
        if isinstance(node.ctx, ast.Load):
            self._add(self.uses, node.lineno, node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._add(self.defs, node.lineno, node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED_SET:
            self._add(self.uses, node.target.lineno, node.target.id)
            self._add(self.defs, node.target.lineno, node.target.id)
        else:
            self.visit(node.target)
        self.visit(node.value)


def source_accesses(
    repo_root: Path,
) -> tuple[
    int,
    dict[int, set[str]],
    dict[int, set[str]],
    dict[int, set[str]],
]:
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    targets = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "feed_process_params_from_cli"
    ]
    if len(targets) != 1:
        fail(
            "expected exactly one top-level feed_process_params_from_cli "
            f"definition, found {len(targets)}"
        )
    target = targets[0]
    def_line = target.lineno

    collector = FunctionAccessCollector(target)
    collector.visit(target)
    collector.defs.setdefault(def_line, set()).update(
        argument.arg
        for argument in (
            *target.args.posonlyargs,
            *target.args.args,
            *target.args.kwonlyargs,
        )
        if argument.arg in TRACKED_SET
    )
    return def_line, collector.defs, collector.uses, collector.for_iter_uses


def parse_target_events(trace_path: Path) -> list[tuple[str, int]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), int(match.group("line"))))
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "call" for event, _ in events):
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    return events


def build_answer(
    events: list[tuple[str, int]],
    def_line: int,
    definitions: dict[int, set[str]],
    uses: dict[int, set[str]],
    for_iter_uses: dict[int, set[str]],
) -> dict[str, object]:
    current_defs: dict[str, int] | None = None
    counts: Counter[tuple[str, int, int]] = Counter()
    seen_for_iter_lines: set[int] = set()
    invocation_count = 0

    for event, line in events:
        if event == "call":
            invocation_count += 1
            current_defs = {
                variable: def_line for variable in definitions.get(def_line, ())
            }
            seen_for_iter_lines = set()
            continue
        if current_defs is None:
            continue
        if event == "line":
            line_uses = set(uses.get(line, ()))
            if line not in seen_for_iter_lines:
                line_uses.update(for_iter_uses.get(line, ()))
                if line in for_iter_uses:
                    seen_for_iter_lines.add(line)
            for variable in sorted(line_uses):
                if variable not in current_defs:
                    fail(
                        f"use of tracked variable {variable!r} at line {line} "
                        "has no reaching definition"
                    )
                counts[(variable, current_defs[variable], line)] += 1
            for variable in sorted(definitions.get(line, ())):
                current_defs[variable] = line
        elif event == "return":
            current_defs = None

    if invocation_count == 0:
        fail(f"trace contains zero invocations for {TARGET_FUNC}")
    if len(counts) < 10:
        fail(f"only {len(counts)} unique def-use pairs were observed; need at least 10")
    if len(set(counts.values())) < 4:
        fail("def-use counts do not span at least four distinct values")

    return {
        "observed_def_use_pairs": [
            {
                "count": count,
                "def_line": pair_def_line,
                "use_line": use_line,
                "variable": variable,
            }
            for (variable, pair_def_line, use_line), count in sorted(counts.items())
        ]
    }


def question_text() -> str:
    tracked = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    methods = ", ".join(
        f"`{name}`"
        for name in (
            "test_colon_fallback_to_file_suffix",
            "test_conflicting_output_modes",
            "test_empty_cli_with_generated_settings",
            "test_explicit_format_permutation",
            "test_implicit_extension_rotation",
            "test_late_invalid_format_after_valid_prefix",
            "test_mixed_implicit_and_explicit",
            "test_overwrite_explicit_and_stdout",
            "test_overwrite_implicit_outputs",
            "test_preconfigured_feeds_override_cli",
            "test_repeated_uri_redefinitions",
            "test_stdout_interleaved_with_uris",
        )
    )
    return (
        "Run every pytest method in "
        "`scrapy_qa/conf_feed_process_params_from_cli_m4_dataflow/files/"
        "testcase.py::FeedProcessParamsDataFlowTest`: "
        f"{methods}. Pytest identifies each method by appending `::<method-name>` "
        "to that class node id and runs them in its normal collected order. "
        "Aggregate across all of those methods: for all invocations of "
        "`scrapy.utils.conf.feed_process_params_from_cli` in "
        "`scrapy/utils/conf.py`, what observed def-use pairs and observation "
        f"counts occur for exactly these outer-function locals: {tracked}? "
        "Only accesses executed by the target function's own frame count; the "
        "body and frame of its nested `check_valid_format` function are excluded. "
        "An invocation is one `call` of the target function during the complete "
        "test run, numbered 1-based in chronological order, although invocation "
        "numbers are not emitted. Definitions never flow between invocations. "
        "A def is parameter binding or an executed assignment that binds the "
        "named local. Every parameter, including one written on a continuation "
        "line, is defined at the opening `def` line. Mutation through an "
        "attribute, subscription, or method call does not redefine the local "
        "holding that object. A use is an executed evaluation that reads the "
        "named local's current value. The reaching def for a use is the most "
        "recent executed def of that variable in the same invocation with no "
        "intervening def. For an ordinary assignment, right-hand-side uses occur "
        "before its target defs. An augmented assignment such as `score += step` "
        "first uses the old `score` def and then creates a new `score` def on the "
        "same source line. For `for item in collection`, the iterable expression "
        "uses `collection` once when the loop is entered, and the loop header "
        "defines `item` once for each successfully obtained item, before that "
        "iteration's body. An iteration is one successful acquisition of the "
        "next item, equivalently one subsequent execution of the loop body's "
        "first statement; the final exhaustion check is not an iteration. All "
        "bindings and accesses syntactically inside list, set, and dict "
        "comprehensions or generator expressions are excluded, including their "
        "comprehension-local variables. Attribute names and mapping keys are not "
        "locals: for example, evaluating `record.value` uses `record`, not "
        "`value`. One observation is one execution of a use under these rules, "
        "reached by that def; therefore a use in a loop body contributes once per "
        "executed iteration. If a tracked variable had multiple syntactic reads "
        "on the same physical source line, that variable would contribute one use "
        "observation for that execution of the line. `count` is the total number "
        "of observations of the exact `(variable, def_line, use_line)` triple, "
        "summed across every invocation in every listed test method. Report "
        "absolute, 1-based physical source line numbers in the named repository "
        "file as it exists for this run. For a multi-line statement or "
        "expression, assign each def or use to the physical line where that "
        "binding or read begins; parameters are the stated exception. Decorator "
        "and docstring lines do not count unless a tracked local is actually "
        "bound or read there. Return exactly one JSON object with the single key "
        "`observed_def_use_pairs`, whose value is a JSON array. Each array element "
        "has exactly four keys: `count`, `def_line`, and `use_line` as JSON "
        "integers, and `variable` as a JSON string containing the exact source "
        "identifier without `repr()` quotes. Emit one row per unique triple: do "
        "not duplicate a row to represent multiplicity, because `count` carries "
        "that multiplicity. Sort rows by `variable` lexicographically ascending, "
        "then `def_line` numerically ascending, then `use_line` numerically "
        "ascending. Do not include invocation numbers, file names, values, null "
        "placeholders, or any additional keys."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    repo_root = Path(__file__).resolve().parents[3]
    def_line, definitions, uses, for_iter_uses = source_accesses(repo_root)
    answer = build_answer(
        parse_target_events(trace_path),
        def_line,
        definitions,
        uses,
        for_iter_uses,
    )
    payload = {
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
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
