#!/usr/bin/env python3
import argparse
import ast
import builtins
import importlib
import inspect
import json
import re
import sys
from pathlib import Path
from types import ModuleType


TARGET_FILE = "src/instructlab/cli/model/train.py"
TARGET_FUNC = "instructlab.cli.model.train.train"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exc_type>[^:\s]+):)?"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def imported_modules(source_path: Path) -> list[ModuleType]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)

    modules = []
    for name in sorted(names):
        try:
            modules.append(importlib.import_module(name))
        except ImportError:
            continue
    return modules


def exception_classes(modules: list[ModuleType]) -> dict[str, set[str]]:
    by_simple_name: dict[str, set[str]] = {}
    pending = list(modules)
    visited = set()
    while pending:
        module = pending.pop()
        if module.__name__ in visited:
            continue
        visited.add(module.__name__)
        root = module.__name__.split(".", 1)[0]
        for value in vars(module).values():
            if inspect.isclass(value) and issubclass(value, BaseException):
                qualified = f"{value.__module__}.{value.__qualname__}"
                by_simple_name.setdefault(value.__name__, set()).add(qualified)
            elif (
                isinstance(value, ModuleType)
                and value.__name__.split(".", 1)[0] == root
                and value.__name__ not in visited
            ):
                pending.append(value)
    return by_simple_name


def normalize_type(simple_name: str, external: dict[str, set[str]]) -> str:
    candidate = getattr(builtins, simple_name, None)
    if (
        inspect.isclass(candidate)
        and issubclass(candidate, BaseException)
        and candidate.__module__ == "builtins"
    ):
        return candidate.__name__

    matches = sorted(external.get(simple_name, set()))
    if len(matches) != 1:
        fail(
            f"cannot uniquely qualify non-built-in exception {simple_name!r}: "
            f"{matches!r}"
        )
    return matches[0]


def parse_trace(trace_path: Path, external: dict[str, set[str]]) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    observed = set()
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith("/" + TARGET_FILE):
            continue
        target_events.append(match.group("event"))
        if match.group("event") == "exception":
            simple_name = match.group("exc_type")
            if not simple_name:
                fail(f"target exception event lacks a type: {raw_line}")
            observed.add(normalize_type(simple_name, external))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not observed:
        fail(f"trace contains no exception events for {TARGET_FUNC}")
    return sorted(observed)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    external = exception_classes(imported_modules(source_path))
    answer = parse_trace(Path(args.trace_log), external)
    question = (
        "Run exactly the pytest test "
        "`instruct_lab_qa/train_train_m5_exceptions/files/testcase.py::"
        "TestTrainLayeredExceptions::"
        "test_public_cli_mixes_training_failures_and_successes` against this "
        "repository. Pytest ids in this question use the exact "
        "`repo/relative/test_file.py::TestClass::test_method` format (for example, "
        "`checks/test_widget.py::TestWidget::test_generated_case`). Across the "
        "complete run, which concrete exception types are observed in the runtime "
        "frame of exactly `instructlab.cli.model.train.train` from "
        "`src/instructlab/cli/model/train.py`? Count an exception observation each "
        "time an exception is raised by that frame or propagates from a callee into "
        "that active frame, whether the function catches it or it escapes. Thus an "
        "exception that enters this frame and is caught counts, and a new exception "
        "subsequently raised by its handler counts separately. Exclude exceptions "
        "that occur wholly in callees without propagating into this frame, and exclude "
        "events in every other function, including same-named functions. Consider "
        "every invocation made by the named test. An invocation is one runtime call "
        "of exactly this function, numbered 1-based in chronological call order; no "
        "invocation is omitted, but invocation numbers are not part of the output. "
        "Exception type naming MUST use the same convention as S5, stated verbatim "
        "here: bare `type(exc).__name__` for built-ins (e.g. `ValueError`, never "
        "`builtins.ValueError`), `module.QualName` for all others. Report type names "
        "only: do not report `str(exc)`, `repr(exc)`, messages, counts, invocation "
        "numbers, or null/empty placeholders. Remove duplicate type-name strings "
        "across the whole run, then sort the remaining strings in ascending "
        "lexicographic Unicode code-point order. Since duplicates are removed there "
        "is no tie-breaker. Return exactly one JSON object with the single key "
        "`exception_types`; its value must be a non-empty JSON array of JSON strings "
        "in that order, with no additional keys."
    )
    payload = {
        "question_kind": "M5_Exceptions",
        "question": question,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": answer},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
