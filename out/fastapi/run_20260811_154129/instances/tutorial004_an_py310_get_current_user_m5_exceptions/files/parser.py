from __future__ import annotations

import argparse
import builtins
import json
import re
from pathlib import Path

from fastapi import exceptions as fastapi_exceptions
from jwt import exceptions as jwt_exceptions


TARGET_NAME = "docs_src.security.tutorial004_an_py310.get_current_user"

QUESTION = """Run the pytest test `fastapi_qa/tutorial004_an_py310_get_current_user_m5_exceptions/files/testcase.py::TestGeneratedTokenMatrix::test_generated_token_matrix`. Across all direct invocations of `docs_src.security.tutorial004_an_py310.get_current_user` in `docs_src/security/tutorial004_an_py310.py` during that test, report the distinct exception types observed in the target function's frame.

An invocation is one call of the target function and invocations are numbered 1-based in chronological call order, although invocation numbers are not included in the answer. Count an exception when Python reports an exception event in the target's own frame: this includes an exception arriving from a function called by the target even if the target catches it, and an exception explicitly raised by the target whether or not a caller later catches it. Do not count exception events that occur only in callees or callers and are never reported in the target frame. Include every such event from every invocation, then remove duplicate exception types globally.

Exception type naming MUST use bare `type(exc).__name__` for built-ins (for example `ValueError`, never `builtins.ValueError`) and `module.QualName` for all others (for example `sample.errors.WidgetFault`). Return a JSON object with exactly one key, `exception_types`, whose value is a list of these type-name strings. Sort the deduplicated strings in ascending Unicode code-point order. Values are ordinary JSON strings without additional Python `repr()` quotes. Exception messages, test ids, event counts, source line numbers, and invocation numbers are not part of the answer; there is no missing-value placeholder."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def exception_classes() -> dict[str, list[type[BaseException]]]:
    namespaces = (vars(fastapi_exceptions), vars(jwt_exceptions))
    classes: dict[str, list[type[BaseException]]] = {}
    for namespace in namespaces:
        for value in namespace.values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseException)
                and value.__module__ in {"fastapi.exceptions", "jwt.exceptions"}
            ):
                bucket = classes.setdefault(value.__name__, [])
                if value not in bucket:
                    bucket.append(value)
    return classes


def normalize_exception_type(
    raw_name: str, known_classes: dict[str, list[type[BaseException]]]
) -> str:
    builtin = getattr(builtins, raw_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return builtin.__name__

    candidates = known_classes.get(raw_name, [])
    if len(candidates) != 1:
        fail(
            f"could not uniquely resolve non-built-in exception type {raw_name!r}; "
            f"candidate count={len(candidates)}"
        )
    exception_class = candidates[0]
    return f"{exception_class.__module__}.{exception_class.__qualname__}"


def parse_trace(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_lines = [
        line for line in text.splitlines() if f" {TARGET_NAME} event=" in line
    ]
    if not target_lines:
        fail(f"trace contains zero events for {TARGET_NAME}")

    call_count = 0
    exception_names: list[str] = []
    known_classes = exception_classes()
    for line in target_lines:
        event_match = re.search(r"\bevent=(call|line|return|exception)\b", line)
        if event_match is None:
            fail(f"malformed target trace line: {line}")
        event = event_match.group(1)
        if event == "call":
            call_count += 1
        elif event == "exception":
            exception_match = re.search(r"\bexc=([^:\s]+):", line)
            if exception_match is None:
                fail(f"could not parse exception type from target event: {line}")
            exception_names.append(
                normalize_exception_type(exception_match.group(1), known_classes)
            )

    if call_count < 2:
        fail(f"expected multiple target invocations, observed {call_count}")
    if len(exception_names) < 3:
        fail(
            "expected at least three target-frame exception events, "
            f"observed {len(exception_names)}"
        )

    distinct_names = sorted(set(exception_names))
    if len(distinct_names) < 2:
        fail(
            "expected at least two distinct target-frame exception types, "
            f"observed {len(distinct_names)}"
        )
    return {"exception_types": distinct_names}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    main()
