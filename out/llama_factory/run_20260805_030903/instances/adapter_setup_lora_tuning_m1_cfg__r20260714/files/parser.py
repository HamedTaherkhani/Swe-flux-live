import argparse
import dis
import importlib
import json
import os
import sys
from pathlib import Path


TARGET_FUNC_QUALNAME = "llamafactory.model.adapter._setup_lora_tuning"
TARGET_FUNC_NAME = "_setup_lora_tuning"
TARGET_FILE_SUFFIX = "src/llamafactory/model/adapter.py"
TEST_FILE = "llama_factory_qa/adapter_setup_lora_tuning_m1_cfg__r20260714/files/testcase.py"
TEST_CLASS = "TestSetupLoraTuningCFG"
TEST_METHOD = "test_three_distinct_invocation_paths"


def _parse_trace_line(raw_line: str):
    if " event=" not in raw_line:
        return None

    prefix, event_tail = raw_line.rstrip("\n").split(" event=", 1)
    prefix_parts = prefix.strip().split()
    if len(prefix_parts) < 3:
        return None

    file_lineno = prefix_parts[-2]
    qualname = prefix_parts[-1]
    if ":" not in file_lineno:
        return None

    filename, lineno_str = file_lineno.rsplit(":", 1)
    try:
        lineno = int(lineno_str)
    except ValueError:
        return None

    event = event_tail.split(" ", 1)[0]
    return filename.replace("\\", "/"), lineno, qualname, event


def _load_executable_lines() -> list[int]:
    root_dir = Path(__file__).resolve().parents[3]
    src_dir = root_dir / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    module = importlib.import_module("llamafactory.model.adapter")
    fn = getattr(module, TARGET_FUNC_NAME, None)
    if fn is None:
        raise RuntimeError(f"Cannot load target function: {TARGET_FUNC_QUALNAME}")

    executable_lines = sorted({lineno for _offset, lineno in dis.findlinestarts(fn.__code__)})
    if not executable_lines:
        raise RuntimeError("No executable lines discovered for target function.")
    return executable_lines


def _read_trace_events(trace_log: Path):
    if not trace_log.exists():
        raise RuntimeError(f"Trace log does not exist: {trace_log}")
    if trace_log.stat().st_size == 0:
        raise RuntimeError(f"Trace log is empty: {trace_log}")

    events = []
    with trace_log.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            parsed = _parse_trace_line(raw_line)
            if parsed is None:
                continue
            filename, lineno, qualname, event = parsed
            if not filename.endswith(TARGET_FILE_SUFFIX):
                continue
            if not (qualname == TARGET_FUNC_QUALNAME or qualname.endswith(f".{TARGET_FUNC_NAME}")):
                continue
            events.append((filename, lineno, qualname, event))

    if not events:
        raise RuntimeError("Trace contains zero events for the target function.")
    return events


def _build_invocation_line_sets(events):
    invocations = []
    active = None
    call_depth = 0

    for _filename, lineno, _qualname, event in events:
        if event == "call":
            if active is None:
                active = {"ordered_lines": [], "line_set": set()}
            call_depth += 1
            continue

        if active is None:
            continue

        if event == "line":
            active["ordered_lines"].append(lineno)
            active["line_set"].add(lineno)
            continue

        if event in {"return", "exception"}:
            call_depth -= 1
            if call_depth <= 0:
                invocations.append(active)
                active = None
                call_depth = 0

    if active is not None:
        invocations.append(active)

    if not invocations:
        raise RuntimeError("No complete invocations were reconstructed from trace events.")

    if len(invocations) < 3:
        raise RuntimeError(f"Expected at least 3 invocations, observed {len(invocations)}.")

    distinct_paths = {tuple(item["ordered_lines"]) for item in invocations}
    if len(distinct_paths) < 3:
        raise RuntimeError(
            "Expected at least 3 distinct invocation paths; observed "
            f"{len(distinct_paths)} distinct ordered line traces."
        )

    return invocations


def main():
    parser = argparse.ArgumentParser(description="Parse trace and build oracle for adapter_setup_lora_tuning_m1_cfg__r20260714.")
    parser.add_argument("--trace-log", required=True, help="Path to trace log.")
    parser.add_argument("--out", required=True, help="Path to output oracle json.")
    args = parser.parse_args()

    trace_log = Path(args.trace_log)
    out_path = Path(args.out)

    events = _read_trace_events(trace_log)
    invocations = _build_invocation_line_sets(events)
    executable_lines = _load_executable_lines()

    per_invocation_sets = [item["line_set"] for item in invocations]
    union_lines = set().union(*per_invocation_sets)
    always = set(executable_lines)
    for line_set in per_invocation_sets:
        always &= line_set

    sometimes = union_lines - always
    never = set(executable_lines) - union_lines

    if not always or not sometimes or not never:
        raise RuntimeError(
            "Expected non-empty always/sometimes/never sets, got sizes: "
            f"always={len(always)}, sometimes={len(sometimes)}, never={len(never)}."
        )

    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": (
            "For the pytest test `"
            f"{TEST_FILE}::{TEST_CLASS}::{TEST_METHOD}`"
            ", consider every runtime invocation of "
            f"`{TARGET_FUNC_QUALNAME}` in `{TARGET_FILE_SUFFIX}` during that single test run. "
            "Define an invocation as one `call` event for this function paired with its matching "
            "`return`/`exception` event in temporal order. Define an executed line as any source line "
            "number in this function that emits at least one runtime line event during that invocation. "
            "Using the set of executable source line numbers for this function body, return a JSON object "
            "with keys `always_executed`, `sometimes_executed`, and `never_executed` where: "
            "`always_executed` are executable lines seen in every invocation; "
            "`sometimes_executed` are executable lines seen in at least one but not all invocations; and "
            "`never_executed` are executable lines not seen in any invocation. "
            "All three values must be arrays of integers sorted in ascending numeric order."
        ),
        "template_answer": {
            "always_executed": ["int"],
            "sometimes_executed": ["int"],
            "never_executed": ["int"],
        },
        "oracle_answer": {
            "always_executed": sorted(always),
            "sometimes_executed": sorted(sometimes),
            "never_executed": sorted(never),
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(oracle, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
