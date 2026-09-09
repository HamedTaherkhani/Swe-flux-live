import argparse
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.tokenizer_core.TokenizerCore._scan_number"
LOOP_BODY_LINE = 942
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/tokenizer_core\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the pytest class node "
    "`sqlglot_qa/tokenizer_core_scan_number_m2_loops/files/testcase.py::"
    "TestScanNumberLoopBehavior`, which executes once each of all twelve test methods "
    "`test_01_duckdb_underscore_waves`, `test_02_clickhouse_digit_identifiers`, "
    "`test_03_duckdb_scientific_mixture`, `test_04_hive_numeric_suffixes`, "
    "`test_05_spark_suffix_and_exponents`, `test_06_mysql_alphanumeric_boundaries`, "
    "`test_07_postgres_bit_hex_and_decimal`, `test_08_tsql_decimal_boundaries`, "
    "`test_09_bigquery_generated_measurements`, "
    "`test_10_sqlite_incomplete_scientific_forms`, "
    "`test_11_oracle_long_digit_batches`, and "
    "`test_12_snowflake_mixed_numeric_stream`. Aggregate over every invocation during "
    "all of those methods of exactly "
    "`sqlglot.tokenizer_core.TokenizerCore._scan_number` in "
    "`sqlglot/tokenizer_core.py`; calls of any other function are excluded. An "
    "invocation means one Python call of that exact function and invocations are "
    "numbered 1-based in chronological runtime call order across the complete pytest "
    "run. For each invocation, count iterations of the `while True` loop whose header "
    "is at absolute, 1-based source line 941. Iteration N is the Nth execution, in that "
    "invocation's own frame, of the loop body's first executable statement, the `if` "
    "statement beginning at line 942. Thus an invocation that returns before line 942 "
    "has zero iterations. Executions in callees are excluded. Line numbers refer to "
    "the named file as it exists in the repository; for a multi-line statement, an "
    "execution belongs to the line where the statement or expression begins. The "
    "`def` line, comments, and blank lines are not iterations. After retaining every "
    "invocation's count, including duplicate and zero counts, report the greatest and "
    "least counts over the complete run. There is no sorting or deduplication before "
    "taking these extrema, and chronological order is only the invocation-numbering "
    "rule, not a tie-breaker. Return exactly a JSON object with keys "
    "`max_iterations` then `min_iterations`, each having a base-10 JSON integer value; "
    "do not quote the integers and do not add any other keys."
)


def compute_extrema(trace_path: Path) -> dict[str, int]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_event_count = 0
    active_invocations: list[int] = []
    completed_counts: list[int] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_event_count += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            active_invocations.append(0)
        elif event == "line" and line == LOOP_BODY_LINE:
            if not active_invocations:
                raise RuntimeError("loop-body event occurred outside an active invocation")
            active_invocations[-1] += 1
        elif event == "return":
            if not active_invocations:
                raise RuntimeError("target return occurred outside an active invocation")
            completed_counts.append(active_invocations.pop())

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_invocations:
        raise RuntimeError("one or more target invocations did not complete")
    if not completed_counts:
        raise RuntimeError("trace contains no completed target invocations")
    if len(set(completed_counts)) < 6:
        raise RuntimeError("scenario produced fewer than six distinct iteration counts")
    if max(completed_counts) < 25:
        raise RuntimeError("scenario did not produce a sufficiently long loop invocation")

    return {
        "max_iterations": max(completed_counts),
        "min_iterations": min(completed_counts),
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": compute_extrema(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
