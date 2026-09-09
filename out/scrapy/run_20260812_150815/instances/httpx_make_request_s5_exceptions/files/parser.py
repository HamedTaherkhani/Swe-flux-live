from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
from dataclasses import dataclass
from pathlib import Path


TARGET_FUNC = "scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler._make_request"
TARGET_SUFFIX = "scrapy/core/downloader/handlers/_httpx.py"
EVENT_RE = re.compile(
    r"(?P<file>\S*scrapy/core/downloader/handlers/_httpx\.py):(?P<line>\d+) "
    r"scrapy\.core\.downloader\.handlers\._httpx\.HttpxDownloadHandler\._make_request "
    r"event=(?P<event>call|line|return|exception)"
    r"(?: exc=(?P<exc_type>[^: ]+): )?"
)

QUESTION = (
    "During the sole test method "
    "`scrapy_qa/httpx_make_request_s5_exceptions/files/testcase.py::"
    "TestHttpxMakeRequestExceptions::test_generated_failure_matrix`, consider the "
    "complete execution of every `async with` context that the method directly "
    "creates by calling "
    "`scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler._make_request` "
    "in `scrapy/core/downloader/handlers/_httpx.py`. What is the set of concrete "
    "exception types caught inside `_make_request` by its own explicit `except` "
    "clauses across all of those contexts? An exception counts as caught only when "
    "it is raised into the protected suite of the function's `try` statement and "
    "control subsequently enters one of that same statement's matching `except` "
    "clauses. Include the concrete runtime type, rather than the type named by the "
    "clause. Exclude exceptions raised from within an `except` clause as replacement "
    "exceptions, exceptions handled only in callees, and exceptions propagated out "
    "without entering one of these clauses. Remove duplicate type names across all "
    "contexts, then sort the remaining names lexicographically in ascending Unicode "
    "code-point order; there are no further tie-breakers because duplicates are "
    "removed. Exception type naming MUST use this convention: bare "
    "`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never "
    "`builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`haystack.core.errors.PipelineError`). Return exactly "
    '`{"caught_exception_kinds": ["str", ...]}`, where each element is a JSON string '
    "formatted by that naming convention and ordered by the rule above."
)


@dataclass(frozen=True)
class Event:
    sequence: int
    line: int
    kind: str
    exception_type: str | None


def _parse_events(trace_path: Path) -> list[Event]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = [
        Event(
            sequence=index,
            line=int(match.group("line")),
            kind=match.group("event"),
            exception_type=match.group("exc_type"),
        )
        for index, match in enumerate(EVENT_RE.finditer(text))
    ]
    if not events:
        raise RuntimeError(
            f"trace log contains zero events for target function {TARGET_FUNC}"
        )
    if not any(event.kind == "exception" for event in events):
        raise RuntimeError(f"target function has no exception events in {trace_path}")
    return events


def _try_layout(source_path: Path) -> tuple[tuple[int, int], list[tuple[int, int]]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_make_request"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")
    tries = [node for node in ast.walk(target) if isinstance(node, ast.Try)]
    if len(tries) != 1:
        raise RuntimeError(f"expected one try statement in {TARGET_FUNC}, found {len(tries)}")

    try_node = tries[0]
    protected = (
        min(statement.lineno for statement in try_node.body),
        max((statement.end_lineno or statement.lineno) for statement in try_node.body),
    )
    handlers = [
        (
            min(statement.lineno for statement in handler.body),
            max(
                (statement.end_lineno or statement.lineno)
                for statement in handler.body
            ),
        )
        for handler in try_node.handlers
    ]
    if not handlers:
        raise RuntimeError(f"target try statement has no exception handlers in {source_path}")
    return protected, sorted(handlers)


def _normalize_exception_name(name: str) -> str:
    builtin_class = getattr(builtins, name, None)
    if (
        isinstance(builtin_class, type)
        and issubclass(builtin_class, BaseException)
        and builtin_class.__module__ == "builtins"
    ):
        return builtin_class.__name__

    from scrapy.core.downloader.handlers import _httpx

    matches = {
        (candidate.__module__, candidate.__qualname__)
        for candidate in vars(_httpx.httpx).values()
        if isinstance(candidate, type)
        and issubclass(candidate, BaseException)
        and candidate.__name__ == name
    }
    if len(matches) != 1:
        raise RuntimeError(
            f"cannot uniquely normalize traced exception type {name!r}: {sorted(matches)!r}"
        )
    module, qualname = next(iter(matches))
    return f"{module}.{qualname}"


def _caught_exception_kinds(
    events: list[Event],
    protected: tuple[int, int],
    handlers: list[tuple[int, int]],
) -> list[str]:
    caught: set[str] = set()
    for index, event in enumerate(events):
        if (
            event.kind != "exception"
            or event.exception_type is None
            or not protected[0] <= event.line <= protected[1]
        ):
            continue

        entered_handler = False
        for later in events[index + 1 :]:
            if later.kind == "line" and any(
                start <= later.line <= end for start, end in handlers
            ):
                entered_handler = True
                break
            if later.kind in {"exception", "return"}:
                break
        if entered_handler:
            caught.add(_normalize_exception_name(event.exception_type))

    if not caught:
        raise RuntimeError("target caught no exceptions during the traced test")
    return sorted(caught)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    events = _parse_events(args.trace_log)
    source_path = Path(__file__).resolve().parents[3] / TARGET_SUFFIX
    protected, handlers = _try_layout(source_path)
    answer = {
        "caught_exception_kinds": _caught_exception_kinds(
            events, protected, handlers
        )
    }
    document = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, sort_keys=True))


if __name__ == "__main__":
    main()
