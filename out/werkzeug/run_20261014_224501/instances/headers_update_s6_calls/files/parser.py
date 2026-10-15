#!/usr/bin/env python
"""Trace -> oracle.json for headers_update_s6_calls (S6_InterProceduralCFG)."""

import argparse
import importlib
import inspect
import json
import re
import sys

TARGET = "werkzeug.datastructures.headers.Headers.update"
TARGET_INVOCATION = 2  # 1-based
EVENT_RE = re.compile(
    r" (?P<file>\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

TEST_FILE = "werkzeug_qa/headers_update_s6_calls/files/testcase.py"
TEST_ID = f"{TEST_FILE}::TestHeadersUpdateCalls::test_update_sequence"

QUESTION = f"""Consider the pytest test `{TEST_ID}` (test file `{TEST_FILE}`, class `TestHeadersUpdateCalls`, single test method `test_update_sequence`). The test calls the method `werkzeug.datastructures.headers.Headers.update`, defined in `src/werkzeug/datastructures/headers.py`, several times on the same `Headers` object.

Invocations of `Headers.update` are numbered 1, 2, 3, ... in chronological order of their Python-level `call` event (frame entry, in the `sys.settrace` sense) during this single test run. Focus on invocation number {TARGET_INVOCATION}, i.e. the {TARGET_INVOCATION}nd time an `update` frame is entered.

Report the exact ordered sequence of function calls that happen while that invocation's frame is on the call stack (from its entry until it returns), using these inclusion rules:
- Count every Python function frame entered whose code object is defined in a `.py` file under `src/werkzeug/` (any werkzeug module), whether called directly by `update` or transitively by anything it calls (any nesting depth). This includes every method of `Headers` (dunder methods such as `__iter__` and `__init__` included) and module-level helper functions such as those in `headers.py`.
- Exclude the `update` frame itself.
- Exclude frames whose code name starts with `<` - i.e. list/set/dict comprehensions, generator expressions and lambdas (a qualname ending in `.<locals>.<listcomp>` or `.<locals>.<genexpr>` is never listed).
- Generator functions (functions containing `yield`, e.g. `Headers.items`/`Headers.keys`): a generator call is listed exactly once, at the moment its frame first starts executing (the first `next()` on the generator object, NOT when the generator object is created). Later resumptions of an already-started generator frame are NOT listed.
- Functions defined outside `src/werkzeug/` (standard library, `abc`/`isinstance` checks, builtins such as `str`, the test file's own helpers) are not listed.
- Every call is listed separately, in chronological order of entry; repeated calls of the same function are NOT deduplicated.

Answer format: `{{"function_call_order": [{{"file": str, "func": str}}, ...]}}` where each element is one call, in order. `file` is the repo-relative path of the file defining the function (e.g. `src/werkzeug/routing/map.py`). `func` is the dotted name `<module>.<qualname>` using the module's import name `werkzeug....` (no `src.` prefix) and the function's `__qualname__`, e.g. `werkzeug.routing.map.MapAdapter.match` (a module-level function `foo` in `werkzeug.bar` would be `werkzeug.bar.foo`)."""


def resolve_first_line(func: str) -> int:
    """co_firstlineno of the function named by dotted module.qualname."""
    parts = func.split(".")
    for i in range(len(parts) - 1, 0, -1):
        modname = ".".join(parts[:i])
        try:
            obj = importlib.import_module(modname)
        except ImportError:
            continue
        for attr in parts[i:]:
            obj = inspect.getattr_static(obj, attr)
        obj = inspect.unwrap(obj)
        return obj.__code__.co_firstlineno
    raise RuntimeError(f"cannot resolve function {func!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        print(f"ERROR: cannot read trace log: {e}", file=sys.stderr)
        return 1
    if not lines:
        print("ERROR: trace log is empty", file=sys.stderr)
        return 1

    events = []
    for raw in lines:
        m = EVENT_RE.search(raw)
        if m:
            events.append(m.groupdict())

    if not any(e["func"] == TARGET for e in events):
        print("ERROR: no events for target function in trace", file=sys.stderr)
        return 1

    first_line_cache: dict[str, int] = {}
    invocation = 0
    depth = 0  # werkzeug frame depth relative to the collected update frame
    collecting = False
    finished = False
    seq = []
    for e in events:
        ev = e["event"]
        if not collecting:
            if e["func"] == TARGET and ev == "call":
                invocation += 1
                if invocation == TARGET_INVOCATION:
                    collecting = True
                    depth = 1
            continue
        if ev == "call":
            depth += 1
            name = e["func"]
            if "<" in name.rpartition(".")[2]:
                continue
            if name not in first_line_cache:
                first_line_cache[name] = resolve_first_line(name)
            if int(e["line"]) != first_line_cache[name]:
                continue  # generator resumption
            path = e["file"]
            idx = path.find("src/werkzeug/")
            if idx < 0:
                print(f"ERROR: unexpected file {path}", file=sys.stderr)
                return 1
            seq.append({"file": path[idx:], "func": name})
        elif ev == "return":
            depth -= 1
            if depth == 0:
                if e["func"] != TARGET:
                    print("ERROR: stack mismatch", file=sys.stderr)
                    return 1
                finished = True
                break

    if not finished:
        print(f"ERROR: invocation {TARGET_INVOCATION} not found/complete", file=sys.stderr)
        return 1
    if not seq:
        print("ERROR: empty call sequence", file=sys.stderr)
        return 1

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2)
        fh.write("\n")
    print(f"calls: {len(seq)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
