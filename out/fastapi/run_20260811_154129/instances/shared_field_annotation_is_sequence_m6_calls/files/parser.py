from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "fastapi/_compat/shared.py"
TARGET_FUNC = "fastapi._compat.shared.field_annotation_is_sequence"
TRACKED_FUNCTIONS = {
    "fastapi._compat.shared._annotation_is_complex",
    "fastapi._compat.shared._annotation_is_sequence",
    "fastapi._compat.shared.annotation_is_pydantic_v1",
    "fastapi._compat.shared.field_annotation_is_complex",
    "fastapi._compat.shared.field_annotation_is_scalar",
    "fastapi._compat.shared.field_annotation_is_scalar_sequence",
    "fastapi._compat.shared.field_annotation_is_sequence",
    "fastapi._compat.shared.is_bytes_or_nonable_bytes_annotation",
    "fastapi._compat.shared.is_bytes_sequence_annotation",
    "fastapi._compat.shared.is_pydantic_v1_model_class",
    "fastapi._compat.shared.is_uploadfile_or_nonable_uploadfile_annotation",
    "fastapi._compat.shared.is_uploadfile_sequence_annotation",
    "fastapi._compat.shared.lenient_issubclass",
    "fastapi._compat.shared.value_is_sequence",
}

EVENT_RE = re.compile(
    r"(?P<file>\S*fastapi/_compat/shared\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/shared_field_annotation_is_sequence_m6_calls/files/testcase.py::RuntimeSequenceGraphTest::test_generated_annotation_matrix`
against this repository. The primary target is
`fastapi._compat.shared.field_annotation_is_sequence` in
`fastapi/_compat/shared.py`.

Determine which members of the following tracked set execute at least once
while that test runs:

- `fastapi._compat.shared._annotation_is_complex`
- `fastapi._compat.shared._annotation_is_sequence`
- `fastapi._compat.shared.annotation_is_pydantic_v1`
- `fastapi._compat.shared.field_annotation_is_complex`
- `fastapi._compat.shared.field_annotation_is_scalar`
- `fastapi._compat.shared.field_annotation_is_scalar_sequence`
- `fastapi._compat.shared.field_annotation_is_sequence`
- `fastapi._compat.shared.is_bytes_or_nonable_bytes_annotation`
- `fastapi._compat.shared.is_bytes_sequence_annotation`
- `fastapi._compat.shared.is_pydantic_v1_model_class`
- `fastapi._compat.shared.is_uploadfile_or_nonable_uploadfile_annotation`
- `fastapi._compat.shared.is_uploadfile_sequence_annotation`
- `fastapi._compat.shared.lenient_issubclass`
- `fastapi._compat.shared.value_is_sequence`

An invocation means one Python function `call` event for that function during
the test run, whether called directly by the test, transitively, or
recursively. Calls count regardless of which frame is otherwise on the stack;
calls to functions outside the tracked set do not count. A generator
resumption counts as another invocation if Python emits another `call` event
for its frame. Repeated calls, recursive calls, and resumptions affect only
whether a function is covered: emit each covered tracked function exactly
once. Functions with zero invocations are omitted.

Return exactly
`{"covered_functions": [{"file": <string>, "func": <string>}, ...]}`.
For every item, `file` is the repository-relative POSIX path of the file
defining the function, and `func` is the full dotted Python
`module.qualname`; for example, a method could be represented as
`package.module.Widget.run` with file `package/module.py`. Do not use bare
function names. Deduplicate by the complete (`file`, `func`) pair, then sort
the list in ascending lexicographic order by `file`, with `func` as the
ascending tie-breaker. String comparison uses ordinary Unicode code-point
ordering. The result is a JSON object: keys and string values use normal JSON
serialization, and there are no counts, null placeholders, or entries for
uncovered functions."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    events = list(EVENT_RE.finditer(text))
    if not events:
        raise SystemExit("ERROR: trace log contains no parseable target-file events")
    if not any(match.group("func") == TARGET_FUNC for match in events):
        raise SystemExit(
            f"ERROR: trace log contains zero events for target function {TARGET_FUNC}"
        )

    covered = {
        (TARGET_FILE, match.group("func"))
        for match in events
        if match.group("event") == "call"
        and match.group("func") in TRACKED_FUNCTIONS
    }
    if not covered:
        raise SystemExit("ERROR: no tracked function call events were found")

    answer = {
        "covered_functions": [
            {"file": file_name, "func": func_name}
            for file_name, func_name in sorted(covered)
        ]
    }
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
