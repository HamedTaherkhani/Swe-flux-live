import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/spidermiddlewares/referer.py"
TARGET_FUNC = "scrapy.spidermiddlewares.referer.RefererMiddleware.policy"
OBSERVATION_LINE = 384

QUESTION = """Run the complete pytest class `scrapy_qa/referer_policy_m3_state/files/testcase.py::RefererPolicyStateTest`, aggregating over ALL 12 test methods in that class: `test_meta_policy_cycle`, `test_meta_policy_reverse_stride`, `test_header_policy_cycle`, `test_header_case_variants`, `test_meta_comma_lists`, `test_header_comma_lists_with_noise`, `test_invalid_meta_fallbacks`, `test_invalid_header_fallbacks`, `test_meta_precedes_header`, `test_empty_alias_interleaving`, `test_seeded_policy_shuffle`, and `test_meta_import_paths`. During that class run, consider `scrapy.spidermiddlewares.referer.RefererMiddleware.policy` in the repository-relative file `scrapy/spidermiddlewares/referer.py`. What is the sorted set of distinct values taken by the target frame's local variable `cls` at every execution of absolute source line 384 across all invocations initiated by those test methods?

An invocation means one `call` of the target function during the class run; invocations are numbered from 1 in chronological execution order across the methods, although this question aggregates a set and does not report invocation numbers. Observe `cls` on each `line` event for line 384, immediately before the return statement beginning there executes. Include every such event and no call, return, exception, or other-line event. Line numbers are absolute, 1-based line numbers in the named file as it exists in the repository. A line event for a multi-line statement or expression is attributed to the line where that statement or expression begins. The function's `def` line, decorator lines, and non-executed docstring lines are not observation points. Invocations that return or raise before reaching line 384 contribute no observation. At every included event, `cls` has already been assigned by the call beginning on line 381.

Return a JSON object with exactly the key `unique_values`. Its value is a JSON list of strings. For each included observation, compute Python `repr(cls)` on the complete value with no normalization or truncation; class objects therefore use Python's ordinary class-object representation, not their name or `str()` selected separately. The strings use Python spellings inside representations (for example, a boolean in an unrelated container would appear as `True`, not JSON `true`). Remove duplicates only after computing these complete repr strings, where duplicates mean exact string equality. Sort the remaining strings in ascending lexicographic order by their Unicode code points, with ordinary prefix ordering (a proper prefix sorts first); do not use execution order, locale-aware ordering, or case folding. All observed values are present, so do not use an empty string, JSON null, or an omitted list element to represent a missing local."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    observations: list[str] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if (
            match.group("event") != "line"
            or int(match.group("line")) != OBSERVATION_LINE
        ):
            continue

        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse locals at observation line: {exc}")
        if not isinstance(changed_locals, dict):
            fail("locals at observation line are not a dictionary")
        if "cls" not in changed_locals:
            fail("local 'cls' is missing at an observation on line 384")
        value = changed_locals["cls"]
        if not isinstance(value, str):
            fail("traced repr of local 'cls' is not a string")
        observations.append(value)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not observations:
        fail(f"trace contains no line events for target line {OBSERVATION_LINE}")

    unique_values = sorted(set(observations))
    if len(unique_values) < 8:
        fail(
            "expected at least 8 distinct repr values for 'cls', "
            f"found {len(unique_values)}"
        )
    return {"unique_values": unique_values}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
