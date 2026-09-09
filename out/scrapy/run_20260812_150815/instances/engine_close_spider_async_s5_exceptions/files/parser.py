from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
from dataclasses import dataclass
from pathlib import Path


TARGET_FUNC = "scrapy.core.engine.ExecutionEngine.close_spider_async"
TARGET_SUFFIX = "scrapy/core/engine.py"
EVENT_RE = re.compile(
    r"(?P<file>\S*scrapy/core/engine\.py):(?P<line>\d+) "
    r"scrapy\.core\.engine\.ExecutionEngine\.close_spider_async "
    r"event=(?P<event>call|line|return|exception)"
    r"(?: exc=(?P<exc_type>[^: ]+): )?"
)

QUESTION = (
    "During the sole test method "
    "`scrapy_qa/engine_close_spider_async_s5_exceptions/files/testcase.py::"
    "TestCloseSpiderExceptionHandling::test_indirect_close_collects_failures`, "
    "consider invocation 1 of `scrapy.core.engine.ExecutionEngine.close_spider_async` "
    "in `scrapy/core/engine.py`. An invocation means one call event for that exact "
    "function during the test run, numbered from 1 in chronological order. What is "
    "the set of exception types caught inside that invocation by the function's own "
    "explicit `except Exception` handlers? An exception counts only if it arises "
    "while the corresponding protected suite is executing and control then enters "
    "that handler; exclude exceptions merely observed during coroutine suspension "
    "or resumption, exceptions handled in callees, and exceptions propagated out of "
    "the function. Remove duplicate type names, then sort the names lexicographically "
    "in ascending Unicode code-point order. Exception type naming MUST use this "
    "convention: bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` "
    "— never `builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`haystack.core.errors.PipelineError`). Return exactly "
    '`{"caught_exception_kinds": ["str", ...]}`, where every list element is a JSON '
    "string and the list follows the ordering rule above."
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

    events: list[Event] = []
    for match in EVENT_RE.finditer(text):
        events.append(
            Event(
                sequence=len(events),
                line=int(match.group("line")),
                kind=match.group("event"),
                exception_type=match.group("exc_type"),
            )
        )
    if not events:
        raise RuntimeError(
            f"trace log contains zero events for target function {TARGET_FUNC}"
        )
    if not any(event.kind == "call" for event in events):
        raise RuntimeError(f"target function has no call event in {trace_path}")
    return events


def _is_exception_handler(handler: ast.ExceptHandler) -> bool:
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _line_span(nodes: list[ast.stmt]) -> tuple[int, int]:
    if not nodes:
        raise RuntimeError("cannot derive a line span from an empty statement list")
    return min(node.lineno for node in nodes), max(
        node.end_lineno or node.lineno for node in nodes
    )


def _target_tries(source_path: Path) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target: ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "close_spider_async":
            target = node
            break
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for node in ast.walk(target):
        if not isinstance(node, ast.Try):
            continue
        handlers = [handler for handler in node.handlers if _is_exception_handler(handler)]
        if len(handlers) != 1:
            continue
        spans.append((_line_span(node.body), _line_span(handlers[0].body)))
    if not spans:
        raise RuntimeError("target function has no explicit except Exception handlers")
    return sorted(spans)


def _normalize_exception_name(name: str) -> str:
    candidate = getattr(builtins, name, None)
    if (
        isinstance(candidate, type)
        and issubclass(candidate, BaseException)
        and candidate.__module__ == "builtins"
    ):
        return candidate.__name__
    raise RuntimeError(
        "trace records a non-built-in exception without enough module metadata "
        f"to apply the required naming convention: {name}"
    )


def _caught_exception_kinds(
    events: list[Event], spans: list[tuple[tuple[int, int], tuple[int, int]]]
) -> list[str]:
    caught: set[str] = set()
    for (body_start, body_end), (handler_start, handler_end) in spans:
        handler_events = [
            event
            for event in events
            if event.kind == "line" and handler_start <= event.line <= handler_end
        ]
        if not handler_events:
            continue
        handler_entry = min(handler_events, key=lambda event: event.sequence)
        candidates = [
            event
            for event in events
            if event.kind == "exception"
            and body_start <= event.line <= body_end
            and event.sequence < handler_entry.sequence
            and event.exception_type is not None
        ]
        if not candidates:
            raise RuntimeError(
                f"handler at lines {handler_start}-{handler_end} executed without "
                "a preceding exception event in its protected suite"
            )
        caught.add(
            _normalize_exception_name(
                max(candidates, key=lambda event: event.sequence).exception_type or ""
            )
        )
    if not caught:
        raise RuntimeError("target caught no exceptions during the traced invocation")
    return sorted(caught)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_events(args.trace_log)
    source_path = Path(__file__).resolve().parents[3] / TARGET_SUFFIX
    answer = {
        "caught_exception_kinds": _caught_exception_kinds(
            events, _target_tries(source_path)
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
