from __future__ import annotations

"""Whole-repository evidence tracer.

Staged into the container in place of trace_plugin.py, so an instance's own
eval.sh and the shared conftest drive it unchanged: same test command, same
environment, same enable/disable window as the original harvest.

The harvest tracer records only the target function. This one records every
repository line the test executes and how far each function is from the
target in the call chain, which is the code a solver has to have seen to
account for the target's behaviour. No values are recorded.
"""

import json
import os
import sys

TARGET_FILE_SUBSTR = os.environ.get("TRACE_FILE", "").strip().replace("\\", "/")
TARGET_FUNCS = {
    f.strip() for f in os.environ.get("TRACE_FUNC", "").strip().split(",") if f.strip()
}
TRACE_OUT = os.environ.get("TRACE_OUT", "").strip()
ROOT = os.environ.get("EVIDENCE_ROOT", "").strip() or os.getcwd()
ROOT = ROOT.rstrip("/") + "/"
EVIDENCE_OUT = os.environ.get("EVIDENCE_OUT", "").strip() or os.path.join(
    os.path.dirname(os.path.abspath(TRACE_OUT)) if TRACE_OUT else os.getcwd(),
    "evidence.json",
)
_SKIP_PARTS = ("/site-packages/", "/dist-packages/", "/.venv/", "/venv/", "/.tox/")
_OWN_FILES = ("trace_plugin.py", "conftest.py")

UPSTREAM = -1  # executed, but not inside a call made on behalf of the target

_enabled = False
_depths = {}     # id(frame) -> depth of that live frame, or UPSTREAM
_functions = {}  # (file, first line, name) -> {"depth": int, "lines": set}
_in_repo = {}    # filename -> repository-relative path, or None


def _relative(filename):
    cached = _in_repo.get(filename, 0)
    if cached != 0:
        return cached
    # sys.path entries such as "." leave "/./" inside co_filename.
    path = os.path.normpath(filename).replace("\\", "/")
    rel = None
    if path.startswith(ROOT) and not any(part in path for part in _SKIP_PARTS):
        rel = path[len(ROOT):]
        if rel in _OWN_FILES:
            rel = None
    _in_repo[filename] = rel
    return rel


def _qualified(frame):
    code = frame.f_code
    module = frame.f_globals.get("__name__", "")
    qual = getattr(code, "co_qualname", code.co_name)
    return "%s.%s" % (module, qual) if module else qual


def _is_target(frame, filename):
    """Same rule as the harvest tracer, so depth 0 is exactly what it traced."""
    if TARGET_FILE_SUBSTR and TARGET_FILE_SUBSTR not in filename.replace("\\", "/"):
        return False
    if not TARGET_FUNCS:
        return True
    name = _qualified(frame)
    last = name.rpartition(".")[2]
    return any(
        name == t or name.startswith(t + ".") or name.endswith("." + t) or t == last
        for t in TARGET_FUNCS
    )


def _parent_depth(frame):
    back = frame.f_back
    while back is not None:
        depth = _depths.get(id(back))
        if depth is not None:
            return depth
        back = back.f_back
    return UPSTREAM


def _tracer(frame, event, arg):
    if event == "call":
        filename = frame.f_code.co_filename
        rel = _relative(filename)
        parent = _parent_depth(frame)
        if rel is not None and _is_target(frame, filename):
            depth = 0
        elif parent == UPSTREAM:
            depth = UPSTREAM
        else:
            # Only repository frames add distance; a library frame in between
            # passes its caller's depth through.
            depth = parent + 1 if rel is not None else parent
        _depths[id(frame)] = depth
        if rel is None:
            frame.f_trace_lines = False
            return _tracer
        code = frame.f_code
        key = (rel, code.co_firstlineno, getattr(code, "co_qualname", code.co_name))
        entry = _functions.get(key)
        if entry is None:
            entry = _functions[key] = {"depth": depth, "lines": set()}
        elif depth != UPSTREAM and (entry["depth"] == UPSTREAM or depth < entry["depth"]):
            entry["depth"] = depth
        return _make_local(entry)
    return _tracer


def _make_local(entry):
    lines = entry["lines"]

    def local(frame, event, arg):
        if event == "line":
            lines.add(frame.f_lineno)
        elif event == "return":
            _depths.pop(id(frame), None)
        return local

    return local


def _dump():
    files = {}
    for (rel, first, name), entry in _functions.items():
        if not entry["lines"]:
            continue
        files.setdefault(rel, []).append({
            "function": name,
            "first_line": first,
            "depth": entry["depth"],
            "lines": sorted(entry["lines"]),
        })
    for functions in files.values():
        functions.sort(key=lambda item: item["first_line"])
    payload = {
        "schema_version": 1,
        "root": ROOT,
        "trace_file": TARGET_FILE_SUBSTR,
        "trace_funcs": sorted(TARGET_FUNCS),
        "python": "%d.%d" % sys.version_info[:2],
        "files": files,
    }
    parent = os.path.dirname(os.path.abspath(EVIDENCE_OUT))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(EVIDENCE_OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def enable():
    global _enabled
    if _enabled:
        return
    _enabled = True
    sys.settrace(_tracer)


def disable():
    global _enabled
    sys.settrace(None)
    _enabled = False
    _depths.clear()
    # Written after every test so a crash in a later one loses nothing; the
    # function table accumulates across the tests of the run.
    _dump()
