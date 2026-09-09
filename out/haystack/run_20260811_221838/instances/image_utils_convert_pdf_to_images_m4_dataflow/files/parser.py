#!/usr/bin/env python3
import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/components/converters/image/image_utils.py"
TARGET_FUNC = "haystack.components.converters.image.image_utils._convert_pdf_to_images"
TARGET_METHOD = "_convert_pdf_to_images"
TRACKED_VARIABLES = (
    "all_pdf_images",
    "bytestream",
    "height",
    "image",
    "num_pages",
    "page",
    "page_number",
    "page_range",
    "pdf",
    "pdf_bitmap",
    "pil_max_pixels",
    "pixel_limit",
    "pixels_for_target_scale",
    "resolved_page_range",
    "return_base64",
    "scale",
    "size",
    "target_resolution_dpi",
    "target_scale",
    "width",
)

QUESTION = """Run the pytest class node `haystack_qa/image_utils_convert_pdf_to_images_m4_dataflow/files/testcase.py::TestConvertPdfToImagesDataFlow`, which selects and aggregates ALL `test_...` methods defined on that class. Each selected test is identified by its full pytest id `haystack_qa/image_utils_convert_pdf_to_images_m4_dataflow/files/testcase.py::TestConvertPdfToImagesDataFlow::<method_name>`. The requested counts are totals across all selected methods and all target invocations, independent of pytest's method execution order.

For every invocation of `haystack.components.converters.image.image_utils._convert_pdf_to_images` in `haystack/components/converters/image/image_utils.py` during that complete class run, compute the observed reaching-definition/use pairs for exactly these tracked local variables: `all_pdf_images`, `bytestream`, `height`, `image`, `num_pages`, `page`, `page_number`, `page_range`, `pdf`, `pdf_bitmap`, `pil_max_pixels`, `pixel_limit`, `pixels_for_target_scale`, `resolved_page_range`, `return_base64`, `scale`, `size`, `target_resolution_dpi`, `target_scale`, and `width`. Only bindings in the target function's own frame are tracked. An invocation is one `call` of that function; invocations are numbered from 1 in chronological order, although invocation numbers are not emitted.

A definition is a completed runtime write of a tracked variable. Every parameter is defined when its invocation begins, at the function's `def` line. A plain or annotated assignment defines each tracked name in its target after the right-hand side completes; if evaluation raises first, the write does not occur. A `for` target is defined at the loop-header line once per successful item retrieval, before that iteration's body; the exhaustion check does not define it. The iterable expression on a `for` header contributes uses only once when that loop is first entered. Iteration N is the Nth successful item retrieval for that loop in that invocation. In addition, because this question tracks successive container states, the call `all_pdf_images.append(...)` first uses the prior `all_pdf_images` binding and then defines its new container state at the append call's source line after the call completes. Other method calls, attribute writes, and subscript writes do not define a tracked name. If augmented assignment were present, it would first use the old target value and then define the new value after the operation.

A use is one actually evaluated source-level `Name` load of a tracked binding in the target function's own frame. Short-circuited operands and statements skipped by control flow contribute no uses. Two evaluated loads on the same physical line are two observations. A use is paired with the most recent completed definition of the same variable earlier in that invocation; definitions never cross invocation boundaries. One observation is one evaluated use reached by that definition, so a loop-body use counts once on every iteration where it executes. A comprehension has an implicit nested frame: its targets and all loads performed by that nested frame do not define or use the target function's tracked bindings, even when they have the same spelling. However, Python evaluates the comprehension's outermost iterable in the enclosing target frame, so a tracked name loaded there is an enclosing-frame use. If execution raises before a later expression or write, that later operation contributes nothing.

All line numbers are absolute, 1-based line numbers in the named repository file as it exists for this run. For a multi-line statement or expression, attribute each use to the physical line where that particular name load begins and each definition to the physical line where its assignment target or special append call begins, rather than merely to the statement's first line. Parameter definitions use the `def` line. Decorator and docstring lines contribute no events for this calculation.

Return exactly one JSON object with the shape `{"observed_def_use_pairs": [{"count": 2, "def_line": 8, "use_line": 9, "variable": "buffer"}]}`; this is only a format example and none of its values is part of the answer. Each row has exactly four fields: `variable` is the source-level name as a JSON string, and `def_line`, `use_line`, and `count` are JSON integers. `count` is the total observations of that exact `(variable, def_line, use_line)` triple across all invocations in all test methods. Include every positive-count triple and omit every unobserved triple. Each triple is unique in the list; multiplicity appears only in `count`, with no duplicate rows. Sort ascending first by `variable` using Unicode code-point order, then numerically by `def_line`, then numerically by `use_line`. No reported leaf uses `repr`, `str`, an exception-name format, an empty-value marker, or JSON null."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?: |$)"
)


def parse_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        raise ValueError(f"target event has no locals field: {raw_line.rstrip()}")
    value = ast.literal_eval(raw_line.split(marker, 1)[1].strip())
    if not isinstance(value, dict):
        raise ValueError("target event locals field is not a dictionary")
    return value


def target_names(node):
    if isinstance(node, ast.Name):
        yield node
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from target_names(item)


class FunctionModel(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = tracked
        self.uses = Counter()
        self.definitions = {}
        self.loop_targets = {}
        self.comprehension_uses = Counter()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.tracked:
            self.uses[(node.lineno, node.id)] += 1

    def _assignment(self, node, targets):
        self.visit(node.value)
        for target in targets:
            for name in target_names(target):
                if name.id in self.tracked:
                    self.definitions.setdefault(name.lineno, []).append(name.id)

    def visit_Assign(self, node):
        self._assignment(node, node.targets)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
        for name in target_names(node.target):
            if name.id in self.tracked:
                self.definitions.setdefault(name.lineno, []).append(name.id)

    def visit_For(self, node):
        self.visit(node.iter)
        names = [name for name in target_names(node.target) if name.id in self.tracked]
        if names:
            if len(names) != 1:
                raise ValueError("parser only supports one tracked loop target")
            first_body_line = min(item.lineno for item in node.body)
            self.loop_targets[node.lineno] = (names[0].id, first_body_line)
        for item in node.body:
            self.visit(item)
        for item in node.orelse:
            self.visit(item)

    def _visit_comprehension(self, node):
        outer_iterable = node.generators[0].iter
        for item in ast.walk(outer_iterable):
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and item.id in self.tracked:
                self.comprehension_uses[(node.lineno, item.lineno, item.id)] += 1

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return


def source_model(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_METHOD
        ),
        None,
    )
    if function is None:
        raise ValueError(f"could not locate {TARGET_METHOD} in {source_path}")

    model = FunctionModel(set(TRACKED_VARIABLES))
    for statement in function.body:
        model.visit(statement)
    parameters = [
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
        if argument.arg in TRACKED_VARIABLES
    ]
    return (
        function.lineno,
        parameters,
        model.uses,
        model.definitions,
        model.loop_targets,
        model.comprehension_uses,
    )


def literal_value(value_repr):
    try:
        return ast.literal_eval(value_repr)
    except (ValueError, SyntaxError) as error:
        raise ValueError(f"could not decode traced local value {value_repr!r}") from error


def read_invocations(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    invocations = []
    current = None
    target_events = 0
    with trace_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            match = EVENT_RE.search(raw_line)
            if not match or match.group("func") != TARGET_FUNC:
                continue
            if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
                continue
            target_events += 1
            record = (match.group("event"), int(match.group("line")), parse_locals(raw_line))
            if record[0] == "call":
                if current is not None:
                    raise ValueError("encountered a nested or unterminated target invocation")
                current = [record]
                invocations.append(current)
            elif current is None:
                raise ValueError("target event appeared before its call event")
            else:
                current.append(record)
                if record[0] == "return":
                    current = None

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if not invocations:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if current is not None:
        raise ValueError("trace ended during a target invocation")
    return invocations


def observed_multiplicity(line, variable, static_multiplicity, state):
    if line == 165 and variable == "num_pages":
        return static_multiplicity if not bool(literal_value(state["page_range"])) else 0
    if line == 168:
        page_number = literal_value(state["page_number"])
        if variable == "page_number":
            return 1 if page_number < 1 else 2
        if variable == "num_pages":
            return 0 if page_number < 1 else static_multiplicity
    return static_multiplicity


def harvest(trace_path, source_path):
    def_line, parameters, uses, definitions, loop_targets, comprehension_uses = source_model(source_path)
    counts = Counter()

    for invocation in read_invocations(trace_path):
        reaching = {name: def_line for name in parameters}
        state = dict(invocation[0][2])
        loop_seen = set()
        comprehension_seen = set()
        records = invocation[1:]

        for index, (event, line, changed) in enumerate(records):
            if event != "line":
                continue
            state.update(changed)
            later = records[index + 1] if index + 1 < len(records) else None
            next_line = next((item[1] for item in records[index + 1 :] if item[0] == "line"), None)
            failed = later is not None and later[0] == "exception" and later[1] == line

            for (use_line, variable), static_multiplicity in uses.items():
                if use_line != line:
                    continue
                if line in loop_targets and line in loop_seen:
                    continue
                multiplicity = observed_multiplicity(line, variable, static_multiplicity, state)
                if multiplicity:
                    if variable not in reaching:
                        raise ValueError(f"use of {variable} at line {line} has no reaching definition")
                    counts[(variable, reaching[variable], use_line)] += multiplicity

            for (trigger_line, use_line, variable), multiplicity in comprehension_uses.items():
                if trigger_line == line and trigger_line not in comprehension_seen:
                    if variable not in reaching:
                        raise ValueError(
                            f"comprehension outer-iterable use of {variable} has no reaching definition"
                        )
                    counts[(variable, reaching[variable], use_line)] += multiplicity
                    comprehension_seen.add(trigger_line)

            if line in loop_targets:
                variable, first_body_line = loop_targets[line]
                loop_seen.add(line)
                if next_line == first_body_line:
                    reaching[variable] = line

            if not failed:
                for variable in definitions.get(line, []):
                    reaching[variable] = line
                if line == 208:
                    reaching["all_pdf_images"] = line

    if not counts:
        raise ValueError("computed no observed def-use pairs")
    return [
        {"count": count, "def_line": definition, "use_line": use, "variable": variable}
        for (variable, definition, use), count in sorted(counts.items())
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise FileNotFoundError(f"target source is missing: {source_path}")
    observed = harvest(Path(args.trace_log), source_path)
    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed},
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
