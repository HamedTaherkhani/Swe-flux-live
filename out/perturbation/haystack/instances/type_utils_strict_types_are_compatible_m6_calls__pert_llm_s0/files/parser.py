import argparse
import ast
import json
import re
import sys
from pathlib import Path


QUESTION_KIND = "M6_InterProceduralCFG"
REPO_FILE = "haystack/core/type_utils.py"
MODULE = "haystack.core.type_utils"
TARGET = f"{MODULE}._strict_types_are_compatible"
TEST_SELECTION = (
    "haystack_qa/type_utils_strict_types_are_compatible_m6_calls/files/"
    "testcase.py::TestStrictTypeUtilsInvocationCounts"
)
EVENT_RE = re.compile(
    r"(?P<file>/\S+):(?P<line>[1-9]\d*) "
    r"(?P<func>[^\s]+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = f"""Run the pytest selection `{TEST_SELECTION}` from the repository root. This selects and runs every `test_...` method in that class; aggregate over all of those methods, rather than reporting per-method results. Pytest identifies each selected method as `{TEST_SELECTION}::METHOD_NAME`. Method execution order does not affect the requested summed counts.

The primary target is `{TARGET}` in `{REPO_FILE}`. Consider the scope consisting of every `def` or `async def` defined directly at module level in exactly `{REPO_FILE}`. Nested functions, closures, lambda bodies, generator-expression and comprehension frames are excluded. Methods (including properties, `__init__`, other dunder methods, and inherited methods) are excluded because they are not functions defined directly at module level; imported functions are also excluded.

For every function in that scope, report its invocation count over the complete selected pytest run. One invocation means one Python `call` event for that function's frame, whether the caller is a test, another in-scope function, or any other frame; include calls reached transitively and recursive calls. Count events from all frames and do not deduplicate them. If a generator or coroutine frame were resumed and Python emitted another `call` event for that resumption, that event would count as another invocation. Events for excluded nested, generator-expression, comprehension, lambda, method, inherited, imported, or other-file frames do not count. A scoped function that never executes must still appear once with `count: 0`.

Function identity is its dotted Python module plus `__qualname__`, represented as a JSON string; for example, a hypothetical module-level function `sample` in `pkg/tools.py` would be `pkg.tools.sample`. The `file` value is the repo-relative POSIX path string `{REPO_FILE}`. Counts are JSON integers.

Return exactly an object with key `invocation_counts`, whose value is a JSON list of objects having exactly the keys `count`, `file`, and `func`. Emit exactly one object per in-scope function. Sort entries by `func` ascending using ordinary Unicode code-point string order, with `file` ascending as the tie-breaker if qualnames ever tie. Do not otherwise reorder or deduplicate entries."""


def module_level_functions(source_path: Path) -> list[str]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot read or parse target source {source_path}: {exc}") from exc
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not names:
        raise RuntimeError(f"no module-level functions found in {source_path}")
    return sorted(names)


def parse_trace(trace_path: Path, scoped_funcs: list[str]) -> dict:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    full_names = {f"{MODULE}.{name}" for name in scoped_funcs}
    counts = {name: 0 for name in full_names}
    target_events = 0
    matched_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(f"/{REPO_FILE}"):
            continue
        matched_events += 1
        func = match.group("func")
        if func == TARGET:
            target_events += 1
        if match.group("event") == "call" and func in counts:
            counts[func] += 1

    if matched_events == 0:
        raise RuntimeError(f"trace log contains no events from {REPO_FILE}")
    if target_events == 0:
        raise RuntimeError(f"trace log contains zero events for target {TARGET}")

    entries = [
        {"count": count, "file": REPO_FILE, "func": func}
        for func, count in counts.items()
    ]
    entries.sort(key=lambda entry: (entry["func"], entry["file"]))
    return {"invocation_counts": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        source_path = Path.cwd() / REPO_FILE
        scoped_funcs = module_level_functions(source_path)
        oracle_answer = parse_trace(Path(args.trace_log), scoped_funcs)
        payload = {
            "question_kind": QUESTION_KIND,
            "question": QUESTION,
            "template_answer": {
                "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
            },
            "oracle_answer": oracle_answer,
        }
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
