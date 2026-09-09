from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/io/catalog_config_resolver.py"
TARGET_FUNC = (
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._resolve_credentials"
)
TRACKED_FUNCTIONS = {
    "kedro.io.catalog_config_resolver.CatalogConfigResolver.__init__",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._extract_patterns",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._pattern_specificity",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._resolve_credentials",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._sort_patterns",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._unresolve_credentials",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config.<locals>._traverse_config",
    "kedro.io.catalog_config_resolver.CatalogConfigResolver.is_pattern",
    "kedro.io.catalog_config_resolver._resolve_credentials",
    "kedro.io.catalog_config_resolver._resolve_credentials.<locals>._resolve_value",
}

EVENT_RE = re.compile(
    r"(?P<file>\S*kedro/io/catalog_config_resolver\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

CALL_LINE_TO_FUNC = {
    51: "kedro.io.catalog_config_resolver._resolve_credentials",
    66: "kedro.io.catalog_config_resolver._resolve_credentials.<locals>._resolve_value",
    110: "kedro.io.catalog_config_resolver.CatalogConfigResolver.__init__",
    183: "kedro.io.catalog_config_resolver.CatalogConfigResolver.is_pattern",
    204: "kedro.io.catalog_config_resolver.CatalogConfigResolver._pattern_specificity",
    225: "kedro.io.catalog_config_resolver.CatalogConfigResolver._sort_patterns",
    273: "kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config",
    303: "kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config.<locals>._traverse_config",
    532: "kedro.io.catalog_config_resolver.CatalogConfigResolver._extract_patterns",
    588: "kedro.io.catalog_config_resolver.CatalogConfigResolver._resolve_credentials",
    642: "kedro.io.catalog_config_resolver.CatalogConfigResolver._unresolve_credentials",
}

QUESTION = """Run the complete pytest test
`kedro_qa/catalog_config_resolver_resolve_credentials_m6_calls/files/testcase.py::TestCatalogConfigResolverCallGraph::test_generated_catalog_construction`.
The primary target is
`kedro.io.catalog_config_resolver.CatalogConfigResolver._resolve_credentials`
in `kedro/io/catalog_config_resolver.py`.

Determine which functions in this exact tracked set execute at least once
during the test:

- `kedro.io.catalog_config_resolver.CatalogConfigResolver.__init__`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._extract_patterns`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._pattern_specificity`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._resolve_credentials`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._sort_patterns`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._unresolve_credentials`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver._validate_pattern_config.<locals>._traverse_config`
- `kedro.io.catalog_config_resolver.CatalogConfigResolver.is_pattern`
- `kedro.io.catalog_config_resolver._resolve_credentials`
- `kedro.io.catalog_config_resolver._resolve_credentials.<locals>._resolve_value`

A tracked function "executes" when Python emits at least one `call` event that
enters a frame whose exact function identity is that listed dotted qualified
name. Function identity is `module` plus the code object's lexical
`__qualname__`, separated by a dot; for example,
`sample.mod.Widget.render`. The `<locals>` component shown above is a literal
part of that identity. Match identities exactly, not by bare-name or suffix
matching.

Include such an event regardless of which function called it or which frames
are already on the stack. Thus a transitively reached function is included
only when it is itself in the tracked set; calls to builtins, library
functions, test functions, and every other unlisted function are ignored.
An invocation is one `call` event for a tracked function during this test,
numbered from 1 in chronological event order if invocation numbering is
needed. Repeated calls and recursive calls each create invocations, but the
function appears only once in the result. For a generator, each Python
`call` event produced when its frame is first entered or resumed is an
invocation; generator resumptions still cannot create duplicate result
entries. Return, line, and exception events do not by themselves establish
coverage.

Return exactly one JSON object with this shape:
`{"covered_functions": [{"file": "...", "func": "..."}]}`.
`covered_functions` is a JSON array containing one object for each covered
tracked function and no object for an uncovered tracked function. In every
object, `file` is the exact repository-relative string
`kedro/io/catalog_config_resolver.py`, and `func` is the exact dotted
qualified-name string defined above. These are ordinary JSON strings copied
from the specified identity and path; do not apply `repr()` or `str()`, add
module prefixes, abbreviate `<locals>`, or use JSON `null` for either value.

Remove duplicate `(file, func)` pairs, then sort the objects in ascending
Unicode code-point order by `file`, with ascending `func` as the tie-breaker.
Equal pairs have no further tie-breaker because they are deduplicated. The
test is expected to cover at least one tracked function, so an empty array,
an empty string, JSON `null`, or an omitted key does not represent a result."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.is_file():
        fail(f"Trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"Trace log is empty: {trace_path}")

    target_events = 0
    covered: set[tuple[str, str]] = set()

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if not match:
                continue
            normalized_file = match.group("file").replace("\\", "/")
            event = match.group("event")
            line_number = int(match.group("line"))

            if TARGET_FILE not in normalized_file:
                continue
            raw_func = match.group("func")
            if raw_func.endswith("._resolve_credentials") and 588 <= line_number <= 640:
                target_events += 1
            if event != "call":
                continue

            func = CALL_LINE_TO_FUNC.get(line_number)
            if func is None:
                continue
            if func not in TRACKED_FUNCTIONS:
                fail(f"Mapped an untracked function identity at line {line_number}: {func}")
            covered.add((TARGET_FILE, func))

    if target_events == 0:
        fail(f"Trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if not covered:
        fail("No tracked functions had a call event")

    return {
        "covered_functions": [
            {"file": file_name, "func": func}
            for file_name, func in sorted(covered)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle_answer = harvest(args.trace_log)
    document = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
