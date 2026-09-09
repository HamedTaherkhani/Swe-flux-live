import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/downloadermiddlewares/httpcompression.py"
TARGET_FUNC = (
    "scrapy.downloadermiddlewares.httpcompression."
    "HttpCompressionMiddleware.process_response"
)

QUESTION = """Run the complete pytest class `scrapy_qa/httpcompression_process_response_m3_state/files/testcase.py::HttpCompressionProcessResponseStateTest`, aggregating over ALL 12 test methods in that class: `test_01_gzip_text_series`, `test_02_deflate_text_series`, `test_03_xgzip_text_series`, `test_04_stacked_known_encodings`, `test_05_decode_until_unknown_encoding`, `test_06_unknown_encoding_blocks_decode`, `test_07_gzip_binary_responses`, `test_08_warning_threshold_crossings`, `test_09_without_stats_collector`, `test_10_unencoded_responses`, `test_11_head_responses_bypass_decoding`, and `test_12_decompression_size_failures`. The covered tests are exactly the pytest ids formed by appending each listed method name to that class id with `::`; pytest executes them in collection order, although the requested result is a set and does not preserve that order. During this complete class run, consider `scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware.process_response` in the repository-relative file `scrapy/downloadermiddlewares/httpcompression.py`.

At every Python `line` event in the target function's own frame, observe the two local variables `content_encoding` and `kwargs` if and only if both are currently bound, and compute the complete Python expression `repr((content_encoding, kwargs))` at that point. This is the repr of one two-tuple containing the current list and dictionary values, not a tuple of two separately formatted strings; consequently it captures both replacement of `content_encoding` and in-place mutation of the `kwargs` dictionary. A line event observes the frame state immediately before the source line attributed to that event executes, so an assignment or mutation first appears at the next line event. Include events from every invocation caused by every listed test method, but exclude `call`, `return`, and `exception` events and all events in callees, wrappers, or other frames. An invocation means one `call` of this target function, numbered from 1 in chronological order across the complete class run; invocations that return or raise before both locals are bound contribute no value.

Source line numbers governing these events are absolute, 1-based lines in the named file as it exists in the repository. For a multi-line statement or expression, its execution is attributed to the line where that statement or expression begins. The function's `def` line, decorator line, and non-executed docstring lines are not line-event observation points. No source line numbers or invocation numbers are included in the answer.

Return a JSON object with exactly the key `unique_values`. Its value is a JSON list of strings. Each string is the complete, untruncated Python `repr()` described above: nested containers use their ordinary whole-container Python repr, bytes retain Python bytes-literal syntax, and values inside the string use Python spellings (for example, a boolean in an unrelated container would be `True`, not JSON `true`). There is no missing-value marker: do not substitute an empty string or JSON null when either local is unbound; simply omit that event. Remove duplicates only after computing each complete repr string, with duplicate meaning exact string equality. Sort the distinct strings in ascending lexicographic order by Unicode code points, using ordinary prefix ordering where a proper prefix sorts first; do not use execution order, locale-aware ordering, numeric interpretation, or case folding."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def _parse_changed_locals(raw: str) -> dict[str, str]:
    try:
        changed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse traced locals dictionary: {exc}")
    if not isinstance(changed, dict):
        fail("traced locals payload is not a dictionary")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in changed.items()):
        fail("traced locals payload does not map names to repr strings")
    return changed


def _materialize_pair(state: dict[str, str]) -> str:
    try:
        content_encoding = ast.literal_eval(state["content_encoding"])
        kwargs = ast.literal_eval(state["kwargs"])
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot materialize complete observed local value: {exc}")
    if not isinstance(content_encoding, list):
        fail("observed 'content_encoding' is not a list")
    if not isinstance(kwargs, dict):
        fail("observed 'kwargs' is not a dictionary")
    return repr((content_encoding, kwargs))


def parse_trace(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    observations: list[str] = []
    state: dict[str, str] | None = None

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        changed = _parse_changed_locals(match.group("locals"))

        if event == "call":
            state = {}
        elif state is None:
            fail("target event encountered outside an invocation")

        state.update(changed)

        if event == "line" and {"content_encoding", "kwargs"} <= state.keys():
            observations.append(_materialize_pair(state))

        if event == "return":
            state = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not observations:
        fail("trace contains no line events where both observed locals are bound")

    unique_values = sorted(set(observations))
    if len(unique_values) < 8:
        fail(f"expected at least 8 distinct observed repr values, found {len(unique_values)}")
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
