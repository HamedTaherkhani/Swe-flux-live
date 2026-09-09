from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_RELATIVE = Path("scripts/stat_utils/cal_ppl.py")
TARGET_NAME = "calculate_ppl"
TRACKED = {
    "batch",
    "batch_size",
    "criterion",
    "cutoff_len",
    "data_args",
    "data_collator",
    "dataloader",
    "dataset",
    "dataset_dir",
    "f",
    "finetuning_args",
    "flatten_labels",
    "flatten_logits",
    "loss_mask",
    "max_samples",
    "model",
    "model_args",
    "model_name_or_path",
    "outputs",
    "perplexities",
    "save_name",
    "sentence_logps",
    "shift_labels",
    "shift_logits",
    "stage",
    "template",
    "token_logps",
    "tokenizer",
    "tokenizer_module",
    "total_ppl",
    "training_args",
    "train_on_prompt",
    "trainset",
}


QUESTION = """Run the pytest test `llama_factory_qa/cal_ppl_calculate_ppl_m4_dataflow/files/testcase.py::TestCalPplRuntime::test_cli_drives_all_training_stages` and consider every invocation of `scripts.stat_utils.cal_ppl.calculate_ppl` whose code is in `scripts/stat_utils/cal_ppl.py`. An invocation is one call of that function during this test, numbered 1-based in chronological call order. Consider only execution in the target function's own frame; do not include activity in callees, comprehensions in callees, or the test helpers.

Report the union across all invocations of the observed reaching-definition/use pairs for exactly these local variables: `batch`, `batch_size`, `criterion`, `cutoff_len`, `data_args`, `data_collator`, `dataloader`, `dataset`, `dataset_dir`, `f`, `finetuning_args`, `flatten_labels`, `flatten_logits`, `loss_mask`, `max_samples`, `model`, `model_args`, `model_name_or_path`, `outputs`, `perplexities`, `save_name`, `sentence_logps`, `shift_labels`, `shift_logits`, `stage`, `template`, `token_logps`, `tokenizer`, `tokenizer_module`, `total_ppl`, `training_args`, `train_on_prompt`, and `trainset`.

A definition is a successfully executed binding of one of those names by a parameter, assignment target (including tuple unpacking), loop target, `with ... as` target, assignment expression, or comprehension target. All parameters are defined at the function's `def` line, line 55, separately on every invocation. A simple, chained, or unpacking assignment's definition line is the 1-based line on which its assignment statement begins, and the binding takes effect only after its right-hand side succeeds. A loop target is defined at the loop header line on each successful iteration before the body runs; evaluating a loop header without obtaining another item does not define the target. A `with ... as` target is defined at the `with` statement's starting line after `__enter__` succeeds. An annotation without a value is not a definition, and mutating an object (for example, calling a method on a list) is not a definition of the variable holding it.

A use is an executed read of the variable's current value by a `Name` expression in the target frame. An ordinary assignment target is not a use. For `x += y`, read `x` using the definition that reached the statement and then define `x` anew at the augmented-assignment's starting line, so augmented assignment is both a use and a definition. If a tracked comprehension-local name existed, its target would be defined on each successful comprehension iteration, its reads would be uses, and its reaching definitions would be confined to that comprehension's scope. Reads of free variables by a comprehension's own implicit frame are excluded because they are not in the target function's frame.

For each executed use, pair it with the most recent definition of the same variable that has taken effect on that invocation and path. Omit a use if no such definition exists. Actual control flow governs observation: definitions and uses in untaken branches do not count. Loop-carried flow does count, including a definition from one iteration reaching a use in a later iteration. If the same source-level pair occurs repeatedly or in multiple invocations, include it only once.

Line numbers are absolute 1-based source lines in `scripts/stat_utils/cal_ppl.py` as it exists in the repository. For a multiline statement, a definition uses the line where the defining statement begins; a use uses the line containing the read identifier in the executed expression. The `def` line can therefore appear as a parameter definition; decorator and docstring lines are not uses or definitions under these rules.

Return exactly one JSON object with key `observed_def_use_pairs`. Its value is a list of objects, each having exactly `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Deduplicate by the complete `(variable, def_line, use_line)` triple, then sort ascending by `variable` (Unicode code-point order), then `def_line`, then `use_line`. There are no rendered runtime values, null sentinels, function names, or exception names in the answer."""


def _target_names(target: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


class FlowFacts(ast.NodeVisitor):
    def __init__(self, function: ast.FunctionDef):
        self.function = function
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}

    def add_defs(self, line: int, names: set[str]) -> None:
        selected = names & TRACKED
        if selected:
            self.defs.setdefault(line, set()).update(selected)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is not self.function:
            return
        parameters = {
            arg.arg
            for arg in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
        }
        if node.args.vararg:
            parameters.add(node.args.vararg.arg)
        if node.args.kwarg:
            parameters.add(node.args.kwarg.arg)
        self.add_defs(node.lineno, parameters)
        for statement in node.body:
            self.visit(statement)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in TRACKED:
            self.uses.setdefault(node.lineno, set()).add(node.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.add_defs(node.lineno, _target_names(target))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self.add_defs(node.lineno, _target_names(node.target))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED:
            self.uses.setdefault(node.lineno, set()).add(node.target.id)
        else:
            self.visit(node.target)
        self.visit(node.value)
        self.add_defs(node.lineno, _target_names(node.target))

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self.add_defs(node.lineno, _target_names(node.target))
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.add_defs(node.lineno, _target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.add_defs(node.lineno, _target_names(node.target))


def load_flow_facts(root: Path) -> FlowFacts:
    source_path = root / TARGET_RELATIVE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == TARGET_NAME
        ),
        None,
    )
    if function is None:
        raise RuntimeError(f"target function {TARGET_NAME!r} was not found in {source_path}")
    facts = FlowFacts(function)
    facts.visit(function)
    return facts


def parse_trace(trace_path: Path, facts: FlowFacts) -> list[dict[str, object]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"\s(?P<file>\S*scripts/stat_utils/cal_ppl\.py):(?P<line>\d+)\s+"
        r"(?P<func>\S*\.calculate_ppl)\s+event=(?P<event>call|line|return|exception)\b"
    )
    events = [
        (int(match.group("line")), match.group("event"))
        for match in event_pattern.finditer(text)
    ]
    if not events:
        raise RuntimeError("trace contains zero events for scripts.stat_utils.cal_ppl.calculate_ppl")
    if not any(event == "line" for _, event in events):
        raise RuntimeError("trace contains zero executed line events for the target function")

    reaching: dict[str, int] | None = None
    pairs: set[tuple[str, int, int]] = set()
    calls = 0
    for line, event in events:
        if event == "call":
            calls += 1
            reaching = {
                variable: line
                for variable in facts.defs.get(line, set())
            }
            continue
        if reaching is None:
            continue
        if event == "line":
            for variable in facts.uses.get(line, set()):
                if variable in reaching:
                    pairs.add((variable, reaching[variable], line))
            for variable in facts.defs.get(line, set()):
                reaching[variable] = line
        elif event == "return":
            reaching = None

    if calls == 0:
        raise RuntimeError("trace contains no target call events")
    if not pairs:
        raise RuntimeError("computed def-use answer is empty")
    return [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        root = Path(__file__).resolve().parents[3]
        facts = load_flow_facts(root)
        answer = parse_trace(args.trace_log, facts)
        document = {
            "question_kind": "M4_DataFlow",
            "question": QUESTION,
            "template_answer": {
                "observed_def_use_pairs": [
                    {"def_line": "int", "use_line": "int", "variable": "str"}
                ]
            },
            "oracle_answer": {"observed_def_use_pairs": answer},
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {args.out} with {len(answer)} observed def-use pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
