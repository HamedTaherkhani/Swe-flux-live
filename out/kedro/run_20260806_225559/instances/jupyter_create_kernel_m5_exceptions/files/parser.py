from __future__ import annotations

import argparse
import builtins
import importlib
import inspect
import json
from pathlib import Path
import re
import types


TARGET_FILE = "kedro/framework/cli/jupyter.py"
TARGET_FUNC = "kedro.framework.cli.jupyter._create_kernel"

QUESTION = """Run the single pytest test `kedro_qa/jupyter_create_kernel_m5_exceptions/files/testcase.py::TestJupyterKernelExceptionEvents::test_mixed_kernel_setup_outcomes` and consider every invocation of `kedro.framework.cli.jupyter._create_kernel` in `kedro/framework/cli/jupyter.py` that occurs while that test method runs. A pytest id is written as the repo-relative test-file path, then `::` and the class, then `::` and the method; for example, `tests/unit/test_widget.py::TestWidget::test_case`.

Report the distinct exception types whose exception events occur in the target function's frame over the whole run. An exception event counts whenever an exception is raised by an operation executing in that frame or propagates from a called operation into that frame, before the target's handler processes it. Include exceptions explicitly raised by the target itself. Do not include exceptions that occur only inside called functions and are handled there without propagating into the target frame, or exceptions in caller frames after the target has returned or raised. Include events from all target invocations: invocation 1 is the first call of the target during the test, invocation 2 the next, and so on in chronological execution order.

Exception type naming MUST use the same convention as S5, stated verbatim in the question: bare `type(exc).__name__` for built-ins (e.g. `ValueError`, never `builtins.ValueError`), `module.QualName` for all others. Normalize each event's type using that rule, then remove duplicate normalized names while retaining only their first occurrence. Emit the resulting `exception_types` list in chronological first-occurrence order across all invocations; do not sort it alphabetically. Runtime event order is the total ordering, so no additional tie-breaker is used.

Return exactly one JSON object of the form `{"exception_types": ["str", "..."]}`, where every list element is a JSON string containing the normalized exception type name. Do not report exception messages, counts, invocation numbers, nulls, or any additional keys."""

EVENT_RE = re.compile(
    rf" (?P<file>\S*{re.escape(TARGET_FILE)}):(?P<line>\d+) "
    rf"(?P<func>{re.escape(TARGET_FUNC)}) event=(?P<event>\w+)"
)
EXCEPTION_RE = re.compile(r" event=exception exc=(?P<name>[^: ]+): ")


def normalized_exception_name(short_name: str) -> str:
    builtin_value = getattr(builtins, short_name, None)
    if inspect.isclass(builtin_value) and issubclass(builtin_value, BaseException):
        return short_name

    target_module = importlib.import_module("kedro.framework.cli.jupyter")
    namespaces = [target_module]
    namespaces.extend(
        value
        for value in vars(target_module).values()
        if isinstance(value, types.ModuleType)
    )

    candidates: set[str] = set()
    direct_value = vars(target_module).get(short_name)
    values = [direct_value]
    values.extend(getattr(namespace, short_name, None) for namespace in namespaces)
    for value in values:
        if inspect.isclass(value) and issubclass(value, BaseException):
            candidates.add(f"{value.__module__}.{value.__qualname__}")

    if len(candidates) != 1:
        raise RuntimeError(
            f"Cannot resolve traced non-built-in exception {short_name!r}; "
            f"candidates={sorted(candidates)!r}"
        )
    return next(iter(candidates))


def parse_trace(trace_path: Path) -> list[str]:
    if not trace_path.is_file():
        raise FileNotFoundError(f"Trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"Trace log is empty: {trace_path}")

    target_event_count = 0
    exception_names: list[str] = []
    seen: set[str] = set()

    for line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.search(line)
        if event_match is None:
            continue
        target_event_count += 1
        if event_match.group("event") != "exception":
            continue

        exception_match = EXCEPTION_RE.search(line)
        if exception_match is None:
            raise RuntimeError(f"Malformed target exception event: {line}")
        normalized = normalized_exception_name(exception_match.group("name"))
        if normalized not in seen:
            seen.add(normalized)
            exception_names.append(normalized)

    if target_event_count == 0:
        raise RuntimeError(
            f"Trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not exception_names:
        raise RuntimeError(f"Trace contains zero exception events for {TARGET_FUNC}")
    return exception_names


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": parse_trace(arguments.trace_log)},
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
