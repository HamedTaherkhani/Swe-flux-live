from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FUNC = "scrapy.crawler.Crawler.crawl_async"
TARGET_SUFFIX = "scrapy/crawler.py"
EVENT_RE = re.compile(
    r"(?P<file>\S*scrapy/crawler\.py):(?P<line>\d+) "
    r"scrapy\.crawler\.Crawler\.crawl_async "
    r"event=(?P<event>call|line|return|exception)"
    r"(?: exc=(?P<exc_type>[^: ]+): )?"
)

QUESTION = (
    "Run every test method whose name begins with `test_` in "
    "`scrapy_qa/crawler_crawl_async_m5_exceptions/files/testcase.py::"
    "TestCrawlerCrawlAsyncExceptions` under pytest, and aggregate across all of "
    "those methods. For `scrapy.crawler.Crawler.crawl_async` in "
    "`scrapy/crawler.py`, what are the total per-type counts of exceptions "
    "observed in that exact function frame over the whole run? An invocation "
    "means one call of that exact function, numbered from 1 in chronological "
    "order; include every invocation made by every covered test method. An "
    "exception observation is one exception event that the Python runtime "
    "associates with the exact `Crawler.crawl_async` frame: count an exception "
    "raised by code in that frame or propagated into it from a callee once at "
    "each such target-frame observation. An exception raised and fully handled "
    "inside a callee does not count. If the same exception object is re-raised "
    "or otherwise observed again in the same target frame, count that later "
    "observation again; do not deduplicate observations. Counts are totals over "
    "all invocations and all test methods, so repeated observations of one type "
    "in different methods or invocations each contribute to its count. "
    "Exception type naming MUST use this convention: bare `type(exc).__name__` "
    "for built-in exceptions (e.g. `ValueError`, never `builtins.ValueError`), "
    "`module.QualName` for all others. Message = exact `str(exc)`. Exception "
    "messages are not part of this answer. Emit exactly "
    '`{"exception_type_counts": [{"count": <JSON integer>, "exception_type": '
    '"<JSON string>"}, ...]}` with one object for every observed type. Sort '
    "objects by `exception_type` in ascending Unicode code-point order. There "
    "is no secondary tie-break: equal normalized names denote the same type and "
    "must be aggregated into one object."
)


def _read_events(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    matches = list(EVENT_RE.finditer(text))
    if not matches:
        raise RuntimeError(
            f"trace log contains zero events for target function {TARGET_FUNC}"
        )
    if not any(match.group("event") == "call" for match in matches):
        raise RuntimeError(f"target function has no call event in {trace_path}")

    exception_names = [
        match.group("exc_type")
        for match in matches
        if match.group("event") == "exception" and match.group("exc_type")
    ]
    if not exception_names:
        raise RuntimeError(f"target function has no exception events in {trace_path}")
    return exception_names


def _imported_exception_names(source_path: Path) -> dict[str, str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    resolved: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            local_name = alias.asname or alias.name
            candidate = getattr(module, alias.name, None)
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseException)
                and candidate.__module__ != "builtins"
            ):
                resolved[local_name] = (
                    f"{candidate.__module__}.{candidate.__qualname__}"
                )
    return resolved


def _normalize_exception_name(name: str, imported: dict[str, str]) -> str:
    candidate = getattr(builtins, name, None)
    if (
        isinstance(candidate, type)
        and issubclass(candidate, BaseException)
        and candidate.__module__ == "builtins"
    ):
        return candidate.__name__
    if name in imported:
        return imported[name]
    raise RuntimeError(
        "cannot apply the required module.QualName convention to traced "
        f"exception type {name!r}"
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path(__file__).resolve().parents[3] / TARGET_SUFFIX
    imported = _imported_exception_names(source_path)
    counts = Counter(
        _normalize_exception_name(name, imported)
        for name in _read_events(args.trace_log)
    )
    answer = {
        "exception_type_counts": [
            {"count": counts[name], "exception_type": name}
            for name in sorted(counts)
        ]
    }
    document = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(document, sort_keys=True))


if __name__ == "__main__":
    main()
