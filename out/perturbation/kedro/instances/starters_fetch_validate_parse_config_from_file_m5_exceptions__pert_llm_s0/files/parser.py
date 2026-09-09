from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType


TARGET_FILE = "kedro/framework/cli/starters.py"
TARGET_FUNC = "kedro.framework.cli.starters._fetch_validate_parse_config_from_file"
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?P<details>.*)$"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<type>[^:\s]+): .*? locals=")

QUESTION = """Run exactly this pytest test against the repository:
`kedro_qa/starters_fetch_validate_parse_config_from_file_m5_exceptions/files/testcase.py::TestGeneratedConfigExceptionLayers::test_indirect_generated_config_matrix`.
Across the whole test run, what distinct exception types are observed in Python
`exception` trace events delivered to the exact target frame
`kedro.framework.cli.starters._fetch_validate_parse_config_from_file` in
`kedro/framework/cli/starters.py`?

An invocation means one Python `call` event for that exact target function;
invocations are numbered 1-based in chronological call-event order. Consider
every invocation made during the named pytest item, including invocations that
finish normally and invocations that terminate by propagating an exception.
An exception is observed when Python delivers an `exception` event to the
exact target frame. Include exceptions raised by the target itself and
exceptions raised in a callee and propagated into that frame, whether the
target subsequently catches the exception, replaces or re-raises it, or lets
it propagate. Thus, multiple exception events in one invocation all count.
Exclude exception events delivered only to caller, callee, test, or other
frames. Count only `exception` events, not `call`, `line`, or `return` events.

Normalize each observed exception type before deduplication. For built-in
exceptions, use bare `type(exc).__name__` (for example, `ValueError`, never
`builtins.ValueError`). For every non-built-in exception, use
`type(exc).__module__ + "." + type(exc).__qualname__` (for example,
`sample.errors.WidgetFailure`). These are plain JSON strings: do not apply
`repr()`, do not include representation quotes, and do not include exception
messages. Remove duplicate normalized strings across all invocations, then
sort the remaining strings in ascending lexicographic order by Unicode code
point. Deduplication occurs before sorting; there is no event-order or
invocation-order tie-breaker because equal strings have been removed.

The complete answer must be one JSON object with exactly the shape
`{"exception_types": ["str"]}`. `exception_types` is the sorted JSON array
defined above, each element is a JSON string, and `"str"` is a type
placeholder rather than an answer value. Include exactly this key and no
additional fields. If no exception events were observed, the array would be
empty rather than JSON `null` or an omitted key."""


def _walk_exception_classes() -> list[type[BaseException]]:
    classes: list[type[BaseException]] = []
    pending = list(BaseException.__subclasses__())
    seen: set[type[BaseException]] = set()
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        classes.append(candidate)
        try:
            pending.extend(candidate.__subclasses__())
        except TypeError:
            continue
    return classes


def _qualified_exception_name(raw_name: str) -> str:
    builtin = getattr(builtins, raw_name, None)
    if (
        isinstance(builtin, type)
        and issubclass(builtin, BaseException)
        and builtin.__module__ == "builtins"
    ):
        return builtin.__name__

    target_module = importlib.import_module("kedro.framework.cli.starters")
    direct = {
        value
        for value in vars(target_module).values()
        if isinstance(value, type)
        and issubclass(value, BaseException)
        and value.__name__ == raw_name
    }
    if len(direct) == 1:
        exception_class = direct.pop()
        return f"{exception_class.__module__}.{exception_class.__qualname__}"

    module_roots = {
        value.__name__
        for value in vars(target_module).values()
        if isinstance(value, ModuleType)
    }
    reachable_classes = {
        exception_class
        for exception_class in _walk_exception_classes()
        if exception_class.__name__ == raw_name
        and any(
            exception_class.__module__ == root
            or exception_class.__module__.startswith(f"{root}.")
            for root in module_roots
        )
    }
    if len(reachable_classes) != 1:
        candidates = sorted(
            f"{candidate.__module__}.{candidate.__qualname__}"
            for candidate in reachable_classes
        )
        raise RuntimeError(
            f"could not uniquely qualify non-built-in exception {raw_name!r}: "
            f"{candidates}"
        )
    exception_class = reachable_classes.pop()
    return f"{exception_class.__module__}.{exception_class.__qualname__}"


def _read_exception_types(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    raw_types: list[str] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            match is None
            or match.group("func") != TARGET_FUNC
            or not match.group("file")
            .replace("\\", "/")
            .endswith(f"/{TARGET_FILE}")
        ):
            continue
        target_events += 1
        if match.group("event") != "exception":
            continue
        exception_match = EXCEPTION_RE.search(match.group("details"))
        if exception_match is None:
            raise RuntimeError(f"malformed target exception event: {raw_line}")
        raw_types.append(exception_match.group("type"))

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not raw_types:
        raise RuntimeError("trace contains no target exception events")

    exception_types = sorted(
        {_qualified_exception_name(raw_type) for raw_type in raw_types}
    )
    return {"exception_types": exception_types}


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": _read_exception_types(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
