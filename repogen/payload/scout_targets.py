#!/usr/bin/env python3
"""Static target miner. Runs INSIDE the benchmark container (stdlib only,
Python 3.7+ compatible). Walks the repo, scores every function on structural
features relevant to runtime-behavior questions, and emits targets.json.

Usage: python scout_targets.py --root /testbed --out /tmp/repogen/targets.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os

EXCLUDE_DIR_PARTS = {
    ".git", "docs", "doc", "examples", "example", "benchmarks", "build",
    "dist", "node_modules", "vendor", "_vendor", "vendored", "third_party",
    "migrations", "__pycache__", ".tox", ".eggs", "site-packages", "logs",
}
EXCLUDE_FILE_PREFIXES = ("test_", "conftest", "setup")
MIN_BODY_LINES = 8
MAX_BODY_LINES = 250
MAX_FILES = 4000


def is_test_path(path):
    parts = path.replace("\\", "/").split("/")
    return any(p in ("tests", "test", "testing") for p in parts)


class FunctionMetrics(ast.NodeVisitor):
    def __init__(self):
        self.branches = 0
        self.for_loops = 0
        self.while_loops = 0
        self.max_loop_nesting = 0
        self.excepts = 0
        self.raises = 0
        self.finallys = 0
        self.calls = 0
        self.called_names = set()
        self.assigns = 0
        self.augassigns = 0
        self.returns = 0
        self.boolops = 0
        self.comprehensions = 0
        self.with_blocks = 0
        self.breaks_continues = 0
        self._loop_depth = 0

    def visit_If(self, node):
        self.branches += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self._enter_loop(node, is_while=False)

    def visit_AsyncFor(self, node):
        self._enter_loop(node, is_while=False)

    def visit_While(self, node):
        self._enter_loop(node, is_while=True)

    def _enter_loop(self, node, is_while):
        if is_while:
            self.while_loops += 1
        else:
            self.for_loops += 1
        self._loop_depth += 1
        if self._loop_depth > self.max_loop_nesting:
            self.max_loop_nesting = self._loop_depth
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Try(self, node):
        self.excepts += len(node.handlers)
        if node.finalbody:
            self.finallys += 1
        self.generic_visit(node)

    def visit_Raise(self, node):
        self.raises += 1
        self.generic_visit(node)

    def visit_Call(self, node):
        self.calls += 1
        func = node.func
        if isinstance(func, ast.Name):
            self.called_names.add(func.id)
        elif isinstance(func, ast.Attribute):
            self.called_names.add(func.attr)
        self.generic_visit(node)

    def visit_Assign(self, node):
        self.assigns += 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.assigns += 1
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self.augassigns += 1
        self.generic_visit(node)

    def visit_Return(self, node):
        self.returns += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.boolops += 1
        self.generic_visit(node)

    def visit_ListComp(self, node):
        self.comprehensions += 1
        self.generic_visit(node)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_With(self, node):
        self.with_blocks += 1
        self.generic_visit(node)

    def visit_Break(self, node):
        self.breaks_continues += 1

    def visit_Continue(self, node):
        self.breaks_continues += 1

    def visit_FunctionDef(self, node):
        # do not descend into nested function definitions
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def end_lineno_of(node):
    end = getattr(node, "end_lineno", None)
    if end is not None:
        return end
    end = node.lineno
    for child in ast.walk(node):
        line = getattr(child, "lineno", None)
        if line is not None and line > end:
            end = line
    return end


def module_name_for(rel_path):
    no_ext = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    parts = no_ext.replace("\\", "/").split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect_functions(tree):
    """Yield (qualname, node, defined_names_in_module)."""
    module_defs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_defs.add(node.name)

    results = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + child.name if prefix else child.name
                results.append((qual, child))
                visit(child, qual + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, (prefix or "") + child.name + ".")

    visit(tree, "")
    return results, module_defs


def score_function(metrics, body_lines):
    complexity = (
        1
        + metrics.branches
        + metrics.for_loops
        + metrics.while_loops
        + metrics.excepts
        + metrics.boolops
    )
    richness = (
        metrics.assigns
        + metrics.augassigns
        + metrics.max_loop_nesting * 2
        + metrics.raises
        + metrics.breaks_continues
        + min(metrics.calls, 10)
    )
    size_bonus = min(body_lines, 80) / 10.0
    return round(complexity * 2 + richness + size_bonus, 2)


def is_qa_dir(name):
    # The staged QA harness/instances dir (e.g. haystack_qa) is not repo code;
    # its tracer/parser files must never become benchmark targets.
    return name.endswith("_qa")


def scout(root, out_path, exclude_dirs=()):
    exclude = EXCLUDE_DIR_PARTS | set(exclude_dirs)
    targets = []
    seen_files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        parts = rel_dir.replace("\\", "/").split("/")
        if set(parts) & exclude or any(is_qa_dir(p) for p in parts) or is_test_path(rel_dir):
            dirnames[:] = []
            continue
        dirnames[:] = [
            d for d in dirnames
            if d not in exclude and not is_qa_dir(d) and not d.startswith(".")
        ]
        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            if fname.startswith(EXCLUDE_FILE_PREFIXES):
                continue
            seen_files += 1
            if seen_files > MAX_FILES:
                break
            fpath = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(fpath, root).replace("\\", "/")
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (SyntaxError, ValueError, OSError):
                continue

            functions, module_defs = collect_functions(tree)
            for qualname, node in functions:
                end_line = end_lineno_of(node)
                body_lines = end_line - node.lineno + 1
                if not (MIN_BODY_LINES <= body_lines <= MAX_BODY_LINES):
                    continue
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue

                metrics = FunctionMetrics()
                for stmt in node.body:
                    metrics.visit(stmt)

                local_calls = sorted(metrics.called_names & module_defs)
                loops = metrics.for_loops + metrics.while_loops
                record = {
                    "file": rel_path,
                    "module": module_name_for(rel_path),
                    "qualname": qualname,
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": end_line,
                    "params": [a.arg for a in node.args.args],
                    "metrics": {
                        "body_lines": body_lines,
                        "branches": metrics.branches,
                        "loops": loops,
                        "while_loops": metrics.while_loops,
                        "max_loop_nesting": metrics.max_loop_nesting,
                        "excepts": metrics.excepts,
                        "raises": metrics.raises,
                        "finallys": metrics.finallys,
                        "calls": metrics.calls,
                        "local_calls": local_calls,
                        "num_local_calls": len(local_calls),
                        "assigns": metrics.assigns,
                        "augassigns": metrics.augassigns,
                        "returns": metrics.returns,
                        "boolops": metrics.boolops,
                        "comprehensions": metrics.comprehensions,
                        "with_blocks": metrics.with_blocks,
                        "breaks_continues": metrics.breaks_continues,
                    },
                    "score": score_function(metrics, body_lines),
                }
                targets.append(record)

    annotate_callers(targets)
    targets.sort(key=lambda t: (-t["score"], t["file"], t["lineno"]))
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"root": root, "targets": targets}, f, indent=2)
    print("scout: wrote %d targets to %s" % (len(targets), out_path))


MAX_CALLERS = 6


def annotate_callers(targets):
    """Invert local_calls into per-target caller lists (same module, among the
    mined functions), one and two hops up. Lets the generation prompt steer
    tests to exercise the target INDIRECTLY through a caller instead of
    invoking it head-on."""
    by_module = {}
    for t in targets:
        by_module.setdefault(t["module"], {}).setdefault(t["name"], []).append(t)

    direct = {}  # id(target) -> list of caller qualnames
    for u in targets:
        for callee_name in u["metrics"].get("local_calls", []):
            for v in by_module.get(u["module"], {}).get(callee_name, []):
                if v is u:
                    continue
                direct.setdefault(id(v), []).append(u)

    for t in targets:
        one_hop = direct.get(id(t), [])
        two_hop = []
        seen = {t["qualname"]} | {c["qualname"] for c in one_hop}
        for c in one_hop:
            for cc in direct.get(id(c), []):
                if cc["qualname"] not in seen:
                    seen.add(cc["qualname"])
                    two_hop.append(cc)
        t["callers"] = sorted({c["qualname"] for c in one_hop})[:MAX_CALLERS]
        t["callers_2hop"] = sorted({c["qualname"] for c in two_hop})[:MAX_CALLERS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/testbed")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--exclude-dir", action="append", default=[],
        help="extra directory name to skip (repeatable; e.g. the QA dir)",
    )
    args = parser.parse_args()
    scout(args.root, args.out, exclude_dirs=args.exclude_dir)


if __name__ == "__main__":
    main()
