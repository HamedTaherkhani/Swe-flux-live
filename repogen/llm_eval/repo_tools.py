from __future__ import annotations

import inspect
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ToolResult:
    ok: bool
    payload: Dict[str, Any]


class _SilentAiderIO:
    encoding = "utf-8"

    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    def tool_output(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def tool_error(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def tool_warning(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def read_text(self, fname: str) -> str:
        try:
            return Path(fname).read_text(encoding=self.encoding, errors="replace")
        except Exception:
            return ""


class _FallbackTokenizer:
    def encode(self, text: str) -> List[int]:
        # Rough token estimate fallback when aider's model tokenizer is unavailable.
        approx = max(1, len(text) // 4)
        return [0] * approx


class _FallbackMainModel:
    def __init__(self) -> None:
        self.tokenizer = _FallbackTokenizer()

    def token_count(self, text: str) -> int:
        return len(self.tokenizer.encode(text))


_REPO_FILE_CACHE: Dict[str, List[str]] = {}
_REPO_MAP_CACHE: Dict[str, str] = {}
INSTANCE_PREVIEW_LIMIT = 60
DEFAULT_REPOMAP_TOKENS = int(os.environ.get("REPOBEHAVE_REPOMAP_MAX_TOKENS", "24000"))
DEFAULT_CHEAP_REPOMAP_MAX_FILES = int(os.environ.get("REPOBEHAVE_CHEAP_REPOMAP_MAX_FILES", "2000"))
MAX_REPOMAP_RESULT_CHARS = int(os.environ.get("REPOBEHAVE_REPOMAP_MAX_CHARS", "120000"))
MAX_READ_FILE_RESULT_CHARS = int(os.environ.get("REPOBEHAVE_READ_FILE_MAX_CHARS", "60000"))
MAX_TOOL_RESULT_JSON_CHARS = int(os.environ.get("REPOBEHAVE_TOOL_RESULT_JSON_MAX_CHARS", "140000"))


def _truncate_text_with_marker(text: str, max_chars: int) -> Tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text) <= max_chars:
        return text, False
    marker = "\n...<truncated>"
    keep = max(0, max_chars - len(marker))
    return text[:keep] + marker, True


def shrink_tool_payload_for_llm(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(payload)

    if name == "get_repo_map":
        repomap = str(out.get("repo_map", "") or "")
        trimmed, did_trim = _truncate_text_with_marker(repomap, MAX_REPOMAP_RESULT_CHARS)
        if did_trim:
            out["repo_map"] = trimmed
            out["repo_map_truncated"] = True
            out["repo_map_original_chars"] = len(repomap)
    elif name == "read_file":
        content = str(out.get("content", "") or "")
        trimmed, did_trim = _truncate_text_with_marker(content, MAX_READ_FILE_RESULT_CHARS)
        if did_trim:
            out["content"] = trimmed
            out["truncated"] = True
            out["content_original_chars"] = len(content)

    for _ in range(4):
        serialized = json.dumps(out, ensure_ascii=False)
        if len(serialized) <= MAX_TOOL_RESULT_JSON_CHARS:
            return out

        if "repo_map" in out and isinstance(out.get("repo_map"), str) and len(out["repo_map"]) > 3000:
            reduced, _ = _truncate_text_with_marker(out["repo_map"], int(len(out["repo_map"]) * 0.6))
            out["repo_map"] = reduced
            out["repo_map_truncated"] = True
            continue
        if "content" in out and isinstance(out.get("content"), str) and len(out["content"]) > 3000:
            reduced, _ = _truncate_text_with_marker(out["content"], int(len(out["content"]) * 0.6))
            out["content"] = reduced
            out["truncated"] = True
            continue
        if "entries" in out and isinstance(out.get("entries"), list) and len(out["entries"]) > 25:
            original = len(out["entries"])
            out["entries"] = out["entries"][: max(25, original // 2)]
            out["entries_truncated"] = True
            out["entries_original_count"] = original
            continue
        break

    fallback: Dict[str, Any] = {
        "ok": bool(out.get("ok", True)),
        "truncated": True,
        "error": "tool result was truncated to fit model context budget",
    }
    if name == "get_repo_map":
        fallback["repo_map"] = str(out.get("repo_map", "") or "")[:2000]
    if name == "read_file":
        fallback["content"] = str(out.get("content", "") or "")[:2000]
    return fallback


class ReadOnlyRepoTools:
    TEXT_SUFFIXES = {
        ".py",
        ".pyi",
        ".md",
        ".txt",
        ".rst",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".sh",
        ".bash",
        ".zsh",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".java",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".sql",
        ".xml",
        ".html",
        ".css",
    }
    IGNORE_DIRS = {".git", ".hg", ".svn", ".tox", ".venv", "venv", "node_modules", "__pycache__"}

    def __init__(
        self,
        *,
        repo_root: Path,
        instance_dir: Path,
        max_read_lines: int,
        repo_map_mode: str = "repomap",
        cheap_repomap_max_files: int = DEFAULT_CHEAP_REPOMAP_MAX_FILES,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.instance_dir = instance_dir.resolve()
        self.max_read_lines = max_read_lines
        self.repo_map_mode = str(repo_map_mode or "repomap").strip().lower()
        self.cheap_repomap_max_files = max(1, int(cheap_repomap_max_files))

        if self.repo_map_mode not in {"repomap", "cheap_repomap", "none"}:
            raise RuntimeError(
                "Invalid repo_map_mode. Expected one of: repomap, cheap_repomap, none"
            )

        if not self.repo_root.exists():
            raise RuntimeError(f"Repository root does not exist: {self.repo_root}")
        if not self.instance_dir.exists():
            raise RuntimeError(f"Instance dir does not exist: {self.instance_dir}")

        self._repomap = self._build_repomap() if self.repo_map_mode == "repomap" else None

    def enabled_tool_names(self) -> List[str]:
        if self.repo_map_mode == "none":
            return ["list_dir", "read_file"]
        return ["get_repo_map", "list_dir", "read_file"]

    def _build_repomap(self) -> Any:
        try:
            from aider.repomap import RepoMap
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "Failed to import aider.repomap.RepoMap. Install with: pip install aider-chat"
            ) from exc

        io_obj = _SilentAiderIO()
        kwargs = {
            "root": str(self.repo_root),
            # Keep RepoMap bounded so one tool call cannot overflow model context.
            "map_tokens": DEFAULT_REPOMAP_TOKENS,
            "io": io_obj,
            "main_model": _FallbackMainModel(),
        }
        try:
            return RepoMap(**kwargs)
        except TypeError:
            # Older/newer signatures.
            sig = inspect.signature(RepoMap.__init__)
            filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
            return RepoMap(**filtered)

    def _all_repo_files(self) -> List[str]:
        key = str(self.repo_root)
        if key in _REPO_FILE_CACHE:
            return _REPO_FILE_CACHE[key]

        out: List[str] = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() and path.suffix.lower() not in self.TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            out.append(str(path))

        _REPO_FILE_CACHE[key] = sorted(out)
        return _REPO_FILE_CACHE[key]

    def _cheap_repomap_files(self) -> List[str]:
        key = f"cheap::{self.repo_root}"
        if key in _REPO_FILE_CACHE:
            return _REPO_FILE_CACHE[key]

        excluded_dir_tokens = {"test", "tests", "testing", "log", "logs", "__pycache__"}
        out: List[str] = []
        for path in self.repo_root.rglob("*.py"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.repo_root)
            rel_parts_lower = [part.lower() for part in rel.parts]
            filename = path.name.lower()

            if filename == "__init__.py":
                continue
            if filename == "conftest.py":
                continue
            if filename.startswith("test_") or filename.endswith("_test.py"):
                continue
            if any(token in excluded_dir_tokens for token in rel_parts_lower[:-1]):
                continue
            # Additional guard for odd logging-oriented python files.
            if filename.endswith(".log.py") or filename.startswith("log_"):
                continue

            out.append(str(path))

        _REPO_FILE_CACHE[key] = sorted(out)
        return _REPO_FILE_CACHE[key]

    def _repo_map_file_count(self) -> int:
        if self.repo_map_mode == "cheap_repomap":
            return len(self._cheap_repomap_files())
        return len(self._all_repo_files())

    def _is_under_allowed_roots(self, p: Path) -> bool:
        try:
            p.relative_to(self.repo_root)
            return True
        except ValueError:
            pass
        try:
            p.relative_to(self.instance_dir)
            return True
        except ValueError:
            return False

    def _known_repo_prefixes(self) -> List[str]:
        base = self.repo_root.name.lower()
        prefixes = {
            base,
            base.replace("-", "_"),
            base.replace("_", "-"),
            "sympy",
            "keras",
            "xarray",
            "faker",
            "telegram",
            "telegram_bot",
            "python-telegram-bot",
        }
        return sorted(x for x in prefixes if x)

    def _to_user_path(self, p: Path) -> str:
        resolved = p.resolve(strict=False)
        try:
            rel = resolved.relative_to(self.repo_root)
            return str(rel) if str(rel) else "."
        except ValueError:
            pass
        try:
            rel = resolved.relative_to(self.instance_dir)
            return str(rel) if str(rel) else "."
        except ValueError:
            return str(resolved)

    def _resolve_user_path(self, raw_path: str) -> Path:
        raw = raw_path.strip()
        if not raw:
            raise ValueError("path cannot be empty")

        candidate_paths: List[Path] = []
        seen_candidates: set = set()
        known_prefixes = self._known_repo_prefixes()

        def _add_candidate(path: Path) -> None:
            key = str(path)
            if key in seen_candidates:
                return
            seen_candidates.add(key)
            candidate_paths.append(path)

        p = Path(raw)
        if p.is_absolute():
            _add_candidate(p)
            parts = p.parts
            if "testbed" in parts:
                idx = parts.index("testbed")
                rel_parts = parts[idx + 1:]
                if rel_parts:
                    testbed_rel = Path(*rel_parts)
                    _add_candidate(self.repo_root / testbed_rel)
                    _add_candidate(self.repo_root / "src" / testbed_rel)
                    if testbed_rel.parts and testbed_rel.parts[0].lower() in known_prefixes:
                        stripped = Path(*testbed_rel.parts[1:]) if len(testbed_rel.parts) > 1 else Path(".")
                        _add_candidate(self.repo_root / stripped)
                        _add_candidate(self.repo_root / "src" / stripped)
                else:
                    _add_candidate(self.repo_root)
            # Some model outputs duplicate repo folder prefix: <repo>/<repo>/...
            resolved_abs = p.resolve(strict=False)
            try:
                rel = resolved_abs.relative_to(self.repo_root)
                if rel.parts and rel.parts[0].lower() in known_prefixes:
                    if len(rel.parts) > 1:
                        _add_candidate(self.repo_root / Path(*rel.parts[1:]))
                    else:
                        # e.g. absolute ".../<repo>/<repo>" while repo_root already points at package root.
                        _add_candidate(self.repo_root)
            except ValueError:
                pass
        else:
            _add_candidate(self.repo_root / p)
            _add_candidate(self.repo_root / "src" / p)
            _add_candidate(self.instance_dir / p)
            _add_candidate(self.instance_dir / "files" / p)

            # Common benchmark hint paths often include top-level package dir
            # (e.g. sympy/core/...) while repo_root is already that package root.
            parts = p.parts
            if len(parts) > 1:
                first = parts[0].lower()
                if first in known_prefixes:
                    stripped = Path(*parts[1:])
                    _add_candidate(self.repo_root / stripped)
                    _add_candidate(self.repo_root / "src" / stripped)
                    _add_candidate(self.instance_dir / stripped)
                    _add_candidate(self.instance_dir / "files" / stripped)
            elif len(parts) == 1 and parts[0].lower() in known_prefixes:
                # e.g. path="sympy" while repo_root is already sympy package root.
                _add_candidate(self.repo_root)

            # Instance fixtures are often under files/<repo_prefix>/...
            for prefix in known_prefixes:
                _add_candidate(self.instance_dir / "files" / prefix / p)

            # tests/qa/... generally lives under instance_dir/files/tests/qa/...
            if str(p).startswith("tests/"):
                _add_candidate(self.instance_dir / "files" / p)
                for prefix in known_prefixes:
                    _add_candidate(self.instance_dir / "files" / prefix / p)

        allowed_candidates: List[Path] = []
        for cand in candidate_paths:
            resolved = cand.resolve(strict=False)
            if self._is_under_allowed_roots(resolved):
                allowed_candidates.append(resolved)

        # Prefer an existing path to avoid unnecessary failed read attempts.
        for resolved in allowed_candidates:
            if resolved.exists():
                return resolved

        # If absolute path points at instance_dir/tests/... but files are under
        # instance_dir/files/tests/..., patch it transparently.
        for resolved in allowed_candidates:
            try:
                rel_to_instance = resolved.relative_to(self.instance_dir)
            except ValueError:
                continue
            if rel_to_instance.parts and rel_to_instance.parts[0] == "tests":
                fixed = (self.instance_dir / "files" / rel_to_instance).resolve(strict=False)
                if self._is_under_allowed_roots(fixed) and fixed.exists():
                    return fixed

        if allowed_candidates:
            return allowed_candidates[0]

        raise ValueError(
            f"path '{raw_path}' is outside allowed roots: {self.repo_root} and {self.instance_dir}"
        )

    def get_repo_map(self, focus_paths: Optional[List[str]] = None) -> ToolResult:
        if self.repo_map_mode == "none":
            return ToolResult(ok=False, payload={"error": "get_repo_map is disabled in repo_map_mode=none"})
        cache_key = f"{self.repo_map_mode}:{self.repo_root}"

        chat_files: List[str] = []
        if focus_paths:
            for p in focus_paths:
                try:
                    rp = self._resolve_user_path(p)
                except ValueError:
                    continue
                if rp.is_file():
                    chat_files.append(str(rp))

        if not chat_files and cache_key in _REPO_MAP_CACHE:
            return ToolResult(
                ok=True,
                payload={
                    "repo_root": self._to_user_path(self.repo_root),
                    "repo_file_count": self._repo_map_file_count(),
                    "focus_file_count": 0,
                    "repo_map": "(cached repo_map already provided earlier in this instance; omitted to save context)",
                    "repo_map_cached": True,
                },
            )

        if self.repo_map_mode == "cheap_repomap":
            cheap_files = self._cheap_repomap_files()
            limited = cheap_files[: self.cheap_repomap_max_files]
            rel_paths = [self._to_user_path(Path(p)) for p in limited]
            header = [
                "Cheap repository map (python file paths only):",
                f"- mode: cheap_repomap",
                f"- total_candidate_files: {len(cheap_files)}",
                f"- returned_files: {len(rel_paths)}",
            ]
            if len(cheap_files) > len(limited):
                header.append(f"- truncated: true ({len(cheap_files) - len(limited)} omitted)")
            repomap_text = "\n".join(header + rel_paths)
            all_file_count = len(cheap_files)
        else:
            all_files = self._all_repo_files()
            try:
                repomap_text = self._repomap.get_repo_map(chat_files=chat_files, other_files=all_files)
            except TypeError:
                # Defensive fallback for positional signatures.
                repomap_text = self._repomap.get_repo_map(chat_files, all_files)
            all_file_count = len(all_files)

        if not chat_files and repomap_text:
            _REPO_MAP_CACHE[cache_key] = repomap_text

        if not repomap_text:
            repomap_text = ""
        repomap_text, repomap_trimmed = _truncate_text_with_marker(repomap_text, MAX_REPOMAP_RESULT_CHARS)

        return ToolResult(
            ok=True,
            payload={
                "repo_root": self._to_user_path(self.repo_root),
                "repo_file_count": all_file_count,
                "focus_file_count": len(chat_files),
                "repo_map": repomap_text,
                "repo_map_truncated": repomap_trimmed,
                "repo_map_mode": self.repo_map_mode,
            },
        )

    def list_dir(self, path: str = ".", max_entries: int = 200) -> ToolResult:
        try:
            target = self._resolve_user_path(path)
        except ValueError as exc:
            return ToolResult(ok=False, payload={"error": str(exc)})

        if not target.exists():
            return ToolResult(ok=False, payload={"error": f"path does not exist: {self._to_user_path(target)}"})
        if not target.is_dir():
            return ToolResult(ok=False, payload={"error": f"not a directory: {self._to_user_path(target)}"})

        max_entries = max(1, min(int(max_entries), 1000))
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: p.name)[:max_entries]:
            entry = {
                "name": item.name,
                "path": self._to_user_path(item),
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    pass
            entries.append(entry)

        return ToolResult(ok=True, payload={"path": self._to_user_path(target), "entries": entries})

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> ToolResult:
        try:
            target = self._resolve_user_path(path)
        except ValueError as exc:
            return ToolResult(ok=False, payload={"error": str(exc)})

        if not target.exists():
            return ToolResult(ok=False, payload={"error": f"path does not exist: {self._to_user_path(target)}"})
        if not target.is_file():
            return ToolResult(ok=False, payload={"error": f"not a file: {self._to_user_path(target)}"})

        start_line = max(1, int(start_line))
        if end_line is None:
            end_line = start_line + self.max_read_lines - 1
        else:
            end_line = max(start_line, int(end_line))
        if end_line - start_line + 1 > self.max_read_lines:
            end_line = start_line + self.max_read_lines - 1

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(ok=False, payload={"error": f"failed reading file: {exc}"})

        lines = text.splitlines()
        total = len(lines)
        s_idx = start_line - 1
        e_idx = min(end_line, total)

        selected = lines[s_idx:e_idx]
        numbered = "\n".join(f"{i + start_line}:{line}" for i, line in enumerate(selected))

        return ToolResult(
            ok=True,
            payload={
                "path": self._to_user_path(target),
                "start_line": start_line,
                "end_line": e_idx,
                "total_lines": total,
                "truncated": False,
                "content": numbered,
            },
        )


TOOL_DESCRIPTIONS = {
    "get_repo_map": "Return repository map context for the repository. Use this first to find relevant files.",
    "list_dir": "List directory entries in allowed roots (repo root and current instance directory).",
    "read_file": "Read file content by line range. Read-only.",
}

TOOL_INPUT_SCHEMAS = {
    "get_repo_map": {
        "type": "object",
        "properties": {
            "focus_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional file paths to focus the repo map.",
            }
        },
    },
    "list_dir": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (absolute under /testbed or relative to repo/instance).",
                "default": ".",
            },
            "max_entries": {
                "type": "integer",
                "default": 200,
                "minimum": 1,
                "maximum": 1000,
            },
        },
    },
    "read_file": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (absolute under /testbed or relative to repo/instance).",
            },
            "start_line": {
                "type": "integer",
                "default": 1,
                "minimum": 1,
            },
            "end_line": {
                "type": "integer",
                "description": "Optional ending line (inclusive). If omitted, reads max_read_lines from start_line.",
                "minimum": 1,
            },
        },
        "required": ["path"],
    },
}
