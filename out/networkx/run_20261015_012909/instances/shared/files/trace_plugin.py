from __future__ import annotations

"""Pytest sys.settrace helper for faker_qa instances (staged as /testbed/trace_plugin.py)."""

import os
import sys
import threading
from datetime import datetime


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


TARGET_FILE_SUBSTR = os.environ.get("TRACE_FILE", "").strip().replace("\\", "/")
_raw_funcs = os.environ.get("TRACE_FUNC", "").strip()
TARGET_FUNCS = {f.strip() for f in _raw_funcs.split(",") if f.strip()}
TRACE_EVENTS = {
    e.strip() for e in os.environ.get("TRACE_EVENTS", "line").split(",") if e.strip()
}
if not TRACE_EVENTS:
    TRACE_EVENTS = {"line"}
TRACE_OUT = os.environ.get("TRACE_OUT", "").strip() or None
TRACE_LIMIT = _int_env("TRACE_LIMIT", 500)
TRACE_MAXLOCALS = _int_env("TRACE_MAXLOCALS", 200)
NO_UNDERSCORE = os.environ.get("TRACE_NO_UNDERSCORE", "1").strip() != "0"
WITH_TIME = os.environ.get("TRACE_TIME", "1").strip() == "1"
LOG_ALL_LINES = os.environ.get("TRACE_LOG_ALL_LINES", "0").strip() == "1"
FULL_LOCALS_ON_RETURN = os.environ.get("TRACE_FULL_LOCALS_ON_RETURN", "1").strip() != "0"

_lock = threading.Lock()
_fh = None
_enabled = False
_open_error = None
_last_locals: dict[int, dict] = {}


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _safe_repr(x, limit: int = TRACE_LIMIT) -> str:
    try:
        s = repr(x)
    except Exception as e:
        s = f"<repr error: {type(e).__name__}: {e}>"
    if limit >= 0 and len(s) > limit:
        s = s[:limit] + "..."
    return s


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _open_log_if_needed() -> None:
    global _fh, _open_error
    if TRACE_OUT and _fh is None and _open_error is None:
        try:
            _ensure_parent_dir(TRACE_OUT)
            _fh = open(TRACE_OUT, "a", buffering=1, encoding="utf-8")
        except Exception as e:
            _open_error = e
            _fh = None


def _emit(line: str) -> None:
    with _lock:
        out = f"{_timestamp()} {line}" if WITH_TIME else line
        if TRACE_OUT:
            _open_log_if_needed()
            if _fh is not None:
                _fh.write(out + "\n")
                _fh.flush()
                return
        print(out)


def _filter_locals(locals_dict: dict) -> dict:
    out = {}
    count = 0
    for k in sorted(locals_dict.keys()):
        if NO_UNDERSCORE and k.startswith("_"):
            continue
        out[k] = _safe_repr(locals_dict[k])
        count += 1
        if TRACE_MAXLOCALS and count >= TRACE_MAXLOCALS:
            out["..."] = f"<truncated locals: first {TRACE_MAXLOCALS}>"
            break
    return out


def _diff_locals(prev: dict, curr: dict) -> dict:
    if not prev:
        return curr
    changed = {}
    for k, v in curr.items():
        if k not in prev or prev[k] != v:
            changed[k] = v
    return changed


def _frame_target_name(frame) -> str:
    mod = frame.f_globals.get("__name__", "")
    code = frame.f_code
    qual = getattr(code, "co_qualname", code.co_name)
    return f"{mod}.{qual}" if mod else qual


def tracer(frame, event: str, arg):
    if event not in TRACE_EVENTS:
        return tracer

    filename = frame.f_code.co_filename.replace("\\", "/")
    file_match = (not TARGET_FILE_SUBSTR) or (TARGET_FILE_SUBSTR in filename)

    funcname = _frame_target_name(frame)
    func_match = (not TARGET_FUNCS) or (
        funcname in TARGET_FUNCS
        or any(funcname.startswith(f"{t}.") for t in TARGET_FUNCS)
        or any(funcname.endswith(f".{t}") for t in TARGET_FUNCS)
        or any(
            (t == funcname.rpartition(".")[2]) or (t == funcname)
            for t in TARGET_FUNCS
        )
    )

    if not (file_match and func_match):
        return tracer

    lineno = frame.f_lineno
    locals_filtered = _filter_locals(frame.f_locals)
    frame_id = id(frame)
    prev_locals = _last_locals.get(frame_id, {})
    changed_locals = _diff_locals(prev_locals, locals_filtered)
    _last_locals[frame_id] = locals_filtered

    if event == "exception":
        try:
            exc_type, exc_val, _tb = arg
            exc_info = (
                f"{getattr(exc_type, '__name__', str(exc_type))}: "
                f"{_safe_repr(exc_val)}"
            )
        except Exception:
            exc_info = "<unable to format exception>"
        _emit(
            f"{filename}:{lineno} {funcname} "
            f"event={event} exc={exc_info} locals={changed_locals}"
        )
    elif event == "return":
        locals_to_log = locals_filtered if FULL_LOCALS_ON_RETURN else changed_locals
        _emit(
            f"{filename}:{lineno} {funcname} "
            f"event={event} retval={_safe_repr(arg)} locals={locals_to_log}"
        )
    elif event == "call":
        _emit(
            f"{filename}:{lineno} {funcname} "
            f"event={event} locals={changed_locals}"
        )
    elif changed_locals or (LOG_ALL_LINES and event == "line"):
        _emit(
            f"{filename}:{lineno} {funcname} "
            f"event={event} locals={changed_locals}"
        )

    if event in ("return", "exception"):
        _last_locals.pop(frame_id, None)

    return tracer


def enable() -> None:
    global _enabled
    if _enabled:
        return
    _enabled = True
    _emit(
        f"[TRACE][START] pid={os.getpid()} TRACE_OUT={TRACE_OUT!r} "
        f"TRACE_FILE={TARGET_FILE_SUBSTR!r} TRACE_FUNCS={sorted(TARGET_FUNCS) if TARGET_FUNCS else 'ALL'} "
        f"TRACE_EVENTS={sorted(TRACE_EVENTS)}"
    )
    sys.settrace(tracer)


def disable() -> None:
    global _fh, _enabled, _open_error
    sys.settrace(None)
    _enabled = False
    _last_locals.clear()
    with _lock:
        if _fh is not None:
            try:
                _fh.flush()
            finally:
                _fh.close()
                _fh = None
        _open_error = None
