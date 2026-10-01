"""Derive trace-grounded checkpoints for one instance.

A checkpoint is an intermediate fact about the harvested execution that a
solver must establish on the way to the final answer. They are arranged as a
ladder, from locating the code to tracking state:

  locate    where the functions are defined
  entry     how often they are invoked, and with which arguments
  path      which statements one invocation executes and how it exits
  workload  how many times its loops iterate
  state     the values it ends with

Ground truth comes only from the harvested trace.log and the source it traced;
no oracle answer, validation result, or evaluation outcome is read.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..complexity import _eval_metadata, _plan_entries, _trace_path
from .trace_model import Activation, TraceModel, parse_trace, split_tail, tail_field

SCHEMA_VERSION = 1
LEVELS = ("locate", "entry", "path", "workload", "state")

MAX_RELATED_FUNCTIONS = 2
MAX_ARGUMENTS = 4
MAX_LOCALS = 4
MAX_LOOPS = 8
MAX_VALUE_CHARS = 200

_SYNTHETIC = ("<listcomp>", "<dictcomp>", "<setcomp>", "<genexpr>", "<lambda>", "<module>")
_SIMPLE_STMTS = (
    ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Return, ast.Raise,
    ast.Assert, ast.Delete, ast.Pass, ast.Break, ast.Continue,
)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_TRIVIAL_VALUES = (None, True, False, 0, "", [], {}, ())


# --------------------------------------------------------------------------
# Source model
# --------------------------------------------------------------------------


@dataclass
class FunctionInfo:
    node: ast.AST
    qualname: str
    start_line: int  # first decorator line, which is where a call event lands
    def_line: int
    params: List[str] = field(default_factory=list)
    suspendable: bool = False


def _own_nodes(node: ast.AST):
    """Walk a function body without entering nested scopes."""
    pending = list(ast.iter_child_nodes(node))
    while pending:
        child = pending.pop()
        yield child
        if not isinstance(child, _SCOPES):
            pending.extend(ast.iter_child_nodes(child))


def index_functions(tree: ast.AST) -> List[FunctionInfo]:
    found: List[FunctionInfo] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                args = child.args
                params = [a.arg for a in getattr(args, "posonlyargs", [])]
                params += [a.arg for a in args.args]
                params += [a.arg for a in args.kwonlyargs]
                if args.vararg:
                    params.append(args.vararg.arg)
                if args.kwarg:
                    params.append(args.kwarg.arg)
                found.append(
                    FunctionInfo(
                        node=child,
                        qualname=qualname,
                        start_line=min([child.lineno] + [d.lineno for d in child.decorator_list]),
                        def_line=child.lineno,
                        params=params,
                        suspendable=any(
                            isinstance(n, (ast.Yield, ast.YieldFrom, ast.Await, ast.AsyncFor, ast.AsyncWith))
                            for n in _own_nodes(child)
                        ),
                    )
                )
                visit(child, f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def statement_map(func: ast.AST) -> Tuple[Dict[int, int], List[int], List[dict]]:
    """Return (line -> line its statement begins on, lines to ignore, loops).

    A traced multi-line statement reports whichever physical line is being
    evaluated, so every line is folded onto the start of its innermost
    statement. `try:` lines are ignored: whether they produce a line event
    depends on the interpreter version.
    """
    mapping: Dict[int, int] = {}
    ignored: List[int] = []
    loops: List[dict] = []

    def span(start: int, end: int, target: int) -> None:
        for line in range(start, end + 1):
            mapping[line] = target

    def visit(stmts: List[ast.stmt]) -> None:
        for stmt in stmts:
            end = getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([stmt.lineno] + [d.lineno for d in stmt.decorator_list])
                span(start, stmt.lineno, stmt.lineno)
                continue
            span(stmt.lineno, end, stmt.lineno)
            if isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
                if not stmt.body or stmt.body[0].lineno != stmt.lineno:
                    ignored.append(stmt.lineno)
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                loop = _loop_probe(stmt)
                if loop:
                    loops.append(loop)
            for name in ("body", "orelse", "finalbody"):
                block = getattr(stmt, name, None)
                if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                    visit(block)
            for handler in getattr(stmt, "handlers", []) or []:
                h_end = getattr(handler, "end_lineno", handler.lineno) or handler.lineno
                span(handler.lineno, h_end, handler.lineno)
                visit(handler.body)
            for case in getattr(stmt, "cases", []) or []:
                pattern = case.pattern
                p_end = getattr(pattern, "end_lineno", pattern.lineno) or pattern.lineno
                span(pattern.lineno, p_end, pattern.lineno)
                visit(case.body)

    visit(getattr(func, "body", []))
    return mapping, sorted(set(ignored)), loops


def _loop_probe(loop: ast.stmt) -> Optional[dict]:
    """A loop is countable when its body opens with a one-line statement on a
    line of its own: that line is then reported exactly once per iteration."""
    if not loop.body:
        return None
    first = loop.body[0]
    header_end = max(
        getattr(n, "end_lineno", loop.lineno) or loop.lineno
        for n in ([loop.test] if isinstance(loop, ast.While) else [loop.target, loop.iter])
    )
    if first.lineno <= header_end:
        return None
    if isinstance(first, _SIMPLE_STMTS):
        if (getattr(first, "end_lineno", first.lineno) or first.lineno) != first.lineno:
            return None
        probe: ast.AST = first
    elif isinstance(first, ast.If):
        if (getattr(first.test, "end_lineno", first.lineno) or first.lineno) != first.lineno:
            return None
        if not first.body or first.body[0].lineno == first.lineno:
            return None
        probe = first.test
    else:
        return None
    if any(isinstance(n, _COMPREHENSIONS) for n in ast.walk(probe)):
        return None
    return {"line": loop.lineno, "body_line": first.lineno}


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------


def parse_value(text: str) -> Tuple[Any, bool]:
    """Parse a traced repr. Only complete Python literals are usable as ground
    truth; object reprs, addresses and truncated values are rejected."""
    if not isinstance(text, str):
        return None, False
    text = text.strip()
    if not text or len(text) > MAX_VALUE_CHARS or "..." in text:
        return None, False
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None, False
    return value, True


def _is_trivial(value: Any) -> bool:
    return any(type(value) is type(t) and value == t for t in _TRIVIAL_VALUES)


# --------------------------------------------------------------------------
# Spec construction
# --------------------------------------------------------------------------


@dataclass
class Unit:
    """One traced function, identified by where its call events land."""

    func: str
    file: str
    rel_file: str
    info: FunctionInfo
    count: int
    first: Optional[Activation]
    label: str = ""


def _is_traced_function(func: str) -> bool:
    return func.rpartition(".")[2] not in _SYNTHETIC


def _relative(path: str, workdir: str) -> str:
    workdir = workdir.rstrip("/") + "/"
    return path[len(workdir):] if path.startswith(workdir) else path.lstrip("/")


def _source_path(run_dir: Path, instance_dir: Path, rel_file: str) -> Optional[Path]:
    marker = f"/{instance_dir.name}/files/"
    if marker in f"/{rel_file}":
        candidate = instance_dir / "files" / f"/{rel_file}".split(marker, 1)[1]
        if candidate.is_file():
            return candidate
    snapshot_root = run_dir / ".llm_repo_snapshot"
    if snapshot_root.is_dir():
        for repo in sorted(p for p in snapshot_root.iterdir() if p.is_dir()):
            candidate = repo / rel_file
            if candidate.is_file():
                return candidate
    return None


def _units(model: TraceModel, run_dir: Path, instance_dir: Path, workdir: str) -> List[Unit]:
    indexes: Dict[str, List[FunctionInfo]] = {}
    units: List[Unit] = []
    for (file, func), ftrace in model.functions.items():
        rel_file = _relative(file, workdir)
        if rel_file not in indexes:
            source = _source_path(run_dir, instance_dir, rel_file)
            try:
                tree = ast.parse(source.read_text(encoding="utf-8", errors="replace")) if source else None
            except (OSError, SyntaxError, ValueError):
                tree = None
            indexes[rel_file] = index_functions(tree) if tree is not None else []
        name = func.rpartition(".")[2]
        for call_line, count in ftrace.calls_by_line.items():
            info = next(
                (
                    i for i in indexes[rel_file]
                    if i.qualname.rpartition(".")[2] == name
                    and call_line in (i.start_line, i.def_line)
                ),
                None,
            )
            if info is None:
                continue  # a generator resume, or source that no longer lines up
            kept = ftrace.kept.get(call_line) or []
            units.append(
                Unit(func=func, file=file, rel_file=rel_file, info=info, count=count,
                     first=kept[0] if kept else None)
            )
    units.sort(key=lambda u: u.first.seq if u.first else 0)
    return units


def _pick_target(units: List[Unit], plan_target: dict) -> Optional[Unit]:
    if not units:
        return None
    qualname = str(plan_target.get("qualname") or "")
    file = str(plan_target.get("file") or "")
    lineno = plan_target.get("lineno")
    for unit in units:
        same_file = not file or unit.rel_file.endswith(file) or file.endswith(unit.rel_file)
        if not same_file:
            continue
        if qualname and unit.info.qualname == qualname:
            return unit
        if lineno and lineno in (unit.info.start_line, unit.info.def_line):
            return unit
    return units[0]


def _exit_of(activation: Activation, mapping: Dict[int, int]) -> Optional[dict]:
    if not activation.closed or activation.return_tail is None:
        return None
    prefix, final_locals = split_tail(activation.return_tail)
    retval = tail_field(prefix, "retval")
    raised = (
        activation.last_event == "exception"
        and activation.last_event_line == activation.return_line
        and (retval or "").strip() == "None"
    )
    exc_type = ""
    if raised and activation.exceptions:
        exc_prefix, _ = split_tail(activation.exceptions[-1][1])
        exc_type = (tail_field(exc_prefix, "exc") or "").partition(":")[0].strip()
    lines = {mapping.get(activation.return_line, activation.return_line)}
    if activation.lines:
        lines.add(mapping.get(activation.lines[-1], activation.lines[-1]))
    return {
        "kind": "exception" if raised else "return",
        "lines": sorted(lines),
        "exception_type": exc_type.rpartition(".")[2],
        "retval": retval,
        "locals": final_locals or {},
    }


def build_spec(run_dir: Path, instance_dir: Path, *, workdir: str = "/testbed",
               plan_entry: Optional[dict] = None) -> dict:
    instance_id = instance_dir.name
    base = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "run_dir": str(run_dir),
        "levels": list(LEVELS),
    }
    trace_path = _trace_path(run_dir, instance_dir)
    if trace_path is None:
        return {**base, "status": "unavailable", "reason": "no harvested trace.log"}

    model = parse_trace(trace_path, is_primary=_is_traced_function, keep_invocations=1)
    units = _units(model, run_dir, instance_dir, workdir)
    plan_entry = plan_entry or {}
    target = _pick_target(units, plan_entry.get("target") or {})
    if target is None:
        return {**base, "status": "unavailable",
                "reason": "no traced function could be aligned with repository source"}

    related = [u for u in units if u is not target][:MAX_RELATED_FUNCTIONS]
    chosen = [target] + related
    seen: Dict[str, int] = {}
    for unit in chosen:
        label = unit.info.qualname
        seen[label] = seen.get(label, 0) + 1
        unit.label = label if seen[label] == 1 else f"{label}@{unit.info.def_line}"

    checkpoints: List[dict] = []
    template: Dict[str, Any] = {"functions": {}}

    for unit in chosen:
        template["functions"][unit.label] = {"def_line": "int", "invocation_count": "int"}
        checkpoints.append({
            "id": f"{unit.label}.def_line", "level": "locate", "kind": "int",
            "path": ["functions", unit.label, "def_line"],
            "expected": unit.info.def_line,
            "accept": sorted({unit.info.def_line, unit.info.start_line}),
        })
        checkpoints.append({
            "id": f"{unit.label}.invocation_count", "level": "entry", "kind": "int",
            "path": ["functions", unit.label, "invocation_count"],
            "expected": unit.count,
        })

    first_block = _first_invocation(target, checkpoints)
    if first_block:
        template["first_invocation"] = first_block

    return {
        **base,
        "status": "ok",
        "category": plan_entry.get("category", ""),
        "trace": str(trace_path),
        "trace_funcs": _eval_metadata(instance_dir)["traced_functions"],
        "target": {
            "label": target.label, "file": target.rel_file,
            "def_line": target.info.def_line, "suspendable": target.info.suspendable,
        },
        "functions": [
            {"label": u.label, "file": u.rel_file, "role": "target" if u is target else "related"}
            for u in chosen
        ],
        "template": template,
        "prompt": _prompt(chosen, target, first_block),
        "checkpoints": checkpoints,
    }


def _first_invocation(target: Unit, checkpoints: List[dict]) -> Dict[str, Any]:
    activation = target.first
    # A generator or coroutine body is split across resumptions, which the
    # trace cannot stitch back into one call.
    if activation is None or target.info.suspendable:
        return {}
    mapping, ignored, loops = statement_map(target.info.node)
    exit_info = _exit_of(activation, mapping)
    if exit_info is None:
        return {}

    block: Dict[str, Any] = {}
    root = ["first_invocation"]
    fold = {str(k): v for k, v in mapping.items() if k != v}

    _, entry_locals = split_tail(activation.call_tail)
    arguments = {}
    for name in target.info.params:
        value, ok = parse_value((entry_locals or {}).get(name, ""))
        if ok:
            arguments[name] = value
    arguments = dict(list(arguments.items())[:MAX_ARGUMENTS])
    if arguments:
        block["arguments"] = {name: "str" for name in arguments}
        for name, value in arguments.items():
            checkpoints.append({
                "id": f"first_invocation.arguments.{name}", "level": "entry", "kind": "value",
                "path": root + ["arguments", name], "expected": repr(value),
            })

    skip = set(ignored) | {target.info.def_line, target.info.start_line}
    executed = sorted({mapping.get(line, line) for line in activation.lines} - skip)
    if executed:
        block["executed_lines"] = ["int"]
        checkpoints.append({
            "id": "first_invocation.executed_lines", "level": "path", "kind": "line_set",
            "path": root + ["executed_lines"], "expected": executed,
            "fold": fold, "ignore": sorted(skip),
        })

    block["exit_kind"] = "str"
    block["exit_line"] = "int"
    block["exception_type"] = "str"
    checkpoints.append({
        "id": "first_invocation.exit_kind", "level": "path", "kind": "enum",
        "path": root + ["exit_kind"], "expected": exit_info["kind"],
    })
    checkpoints.append({
        "id": "first_invocation.exit_line", "level": "path", "kind": "line",
        "path": root + ["exit_line"], "expected": exit_info["lines"][0],
        "accept": exit_info["lines"], "fold": fold,
    })
    if exit_info["kind"] == "exception" and exit_info["exception_type"]:
        checkpoints.append({
            "id": "first_invocation.exception_type", "level": "path", "kind": "name",
            "path": root + ["exception_type"], "expected": exit_info["exception_type"],
        })

    counted = []
    for loop in loops[:MAX_LOOPS]:
        counted.append((loop["line"], sum(1 for line in activation.lines if line == loop["body_line"])))
    if counted:
        block["loop_iterations"] = {str(line): "int" for line, _ in counted}
        for line, iterations in counted:
            checkpoints.append({
                "id": f"first_invocation.loop_iterations.{line}", "level": "workload", "kind": "int",
                "path": root + ["loop_iterations", str(line)], "expected": iterations,
            })

    # The field is present for every exception exit and every literal return,
    # so its presence alone does not reveal how the call ended.
    returned, returned_ok = parse_value(exit_info["retval"] or "")
    if exit_info["kind"] == "exception" or returned_ok:
        block["return_value"] = "str"
        if exit_info["kind"] == "return":
            checkpoints.append({
                "id": "first_invocation.return_value", "level": "state", "kind": "value",
                "path": root + ["return_value"], "expected": repr(returned),
            })

    final_locals = []
    for name, text in sorted(exit_info["locals"].items()):
        value, ok = parse_value(text)
        if not ok:
            continue
        if name in arguments and arguments[name] == value:
            continue
        final_locals.append((name, value))
    final_locals.sort(key=lambda item: (_is_trivial(item[1]), item[0]))
    final_locals = sorted(final_locals[:MAX_LOCALS], key=lambda item: item[0])
    if final_locals:
        block["locals_at_exit"] = {name: "str" for name, _ in final_locals}
        for name, value in final_locals:
            checkpoints.append({
                "id": f"first_invocation.locals_at_exit.{name}", "level": "state", "kind": "value",
                "path": root + ["locals_at_exit", name], "expected": repr(value),
            })
    return block


def _prompt(chosen: List[Unit], target: Unit, first_block: Dict[str, Any]) -> str:
    lines = [
        "Intermediate checkpoints",
        "",
        "Report the intermediate facts below about the same complete run that the "
        "question describes. They are scored independently of the final answer, "
        "so give your best determination for every field.",
        "",
        "Functions (paths are relative to the repository root):",
    ]
    for unit in chosen:
        role = "target" if unit is target else "related"
        lines.append(f"- `{unit.label}` in {unit.rel_file} [{role}]")
    lines += [
        "",
        'For each function under "functions":',
        "- def_line: the line number of its `def` statement.",
        "- invocation_count: how many times it was called during the complete run. "
        "Count calls; resuming a generator or coroutine is not a new call.",
    ]
    if first_block:
        lines += [
            "",
            f'"first_invocation" describes the chronologically first call of `{target.label}` '
            "during that run.",
        ]
        if "arguments" in first_block:
            lines.append(
                "- arguments: the value bound to each listed parameter when the call begins, "
                "written as a Python literal, for example \"'abc'\", \"[1, 2]\" or \"None\"."
            )
        if "executed_lines" in first_block:
            lines.append(
                "- executed_lines: the sorted distinct line numbers of the statements in the "
                "function's own body that executed during this call. Identify a statement by "
                "the line it begins on. A compound statement (if/for/while/with/match) counts "
                "when its header is evaluated, and an `except` clause counts by its own line "
                "when it is entered. Leave out the `def` line, bare `try:`, `else:` and "
                "`finally:` lines, and anything inside nested functions, lambdas or "
                "comprehension bodies."
            )
        lines += [
            '- exit_kind: "return" if the call completed normally, "exception" if an '
            "exception propagated out of it.",
            "- exit_line: the line on which the last statement executed in the function's own "
            "body begins.",
            '- exception_type: the class name of the propagating exception, or "" when '
            'exit_kind is "return".',
        ]
        if "loop_iterations" in first_block:
            lines.append(
                "- loop_iterations: for each listed loop, keyed by the line of its `for` or "
                "`while` statement, the total number of times its body started executing "
                "during this call."
            )
        if "return_value" in first_block:
            lines.append(
                '- return_value: the returned value as a Python literal, or "" if an '
                "exception propagated."
            )
        if "locals_at_exit" in first_block:
            lines.append(
                "- locals_at_exit: the value of each listed local variable when the call "
                "ended, written as a Python literal."
            )
    return "\n".join(lines)


def public_view(spec: dict) -> Optional[dict]:
    """The only part of a spec a solver may see."""
    if spec.get("status") != "ok":
        return None
    return {"prompt": spec["prompt"], "template": spec["template"]}


def plan_entries(run_dir: Path) -> dict:
    return _plan_entries(run_dir)
