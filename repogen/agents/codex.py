"""Codex CLI backend.

Mirrors RepoBehave's run_codex_eval_in_docker.sh: the host's codex bundle (a
static binary plus sibling helpers such as codex-code-mode-host) is copied into
the container and exposed through a wrapper, auth uses OPENAI_API_KEY (API
billing, preferred) or the host's ChatGPT-plan ~/.codex/auth.json, and each task
is one non-interactive `codex exec --json` session whose event stream is
persisted as the trajectory.

The container is the sandbox, so Codex's own sandbox and approvals are bypassed;
web_search is disabled so the agent can only use the repository. Codex has no
separate file-reading tool: it reads files through the shell, so in static
(no-exec) mode the shell stays available and the guard is the sandbox image,
which has no interpreter or project environment.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..config import env_lookup
from ..docker_env import Container
from .base import AgentBackend, AgentResult, ndjson_to_json
from . import register

_CODEX_HOME = "/root/.codex"
_BUNDLE_DIR = "/opt/codex"
_EFFORTS = ("low", "medium", "high", "xhigh")


def find_codex_binary(explicit: str = "") -> Path:
    """`codex` on PATH, else the newest one bundled with the Cursor/ChatGPT
    extension."""
    candidate = explicit or shutil.which("codex") or ""
    if not candidate:
        bundled = sorted(
            Path.home().glob(".cursor/extensions/openai.chatgpt-*/bin/linux-x86_64/codex"),
            key=_version_key,
        )
        candidate = str(bundled[-1]) if bundled else ""
    path = Path(os.path.realpath(candidate)) if candidate else None
    if path is None or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(
            "codex binary not found; install Codex CLI or pass --codex-bin <path>"
        )
    return path


def _version_key(path: Path) -> list[tuple[int, int, str]]:
    extension_dir = path.parents[2].name  # openai.chatgpt-<version>-<platform>
    return [
        (0, int(token), "") if token.isdigit() else (1, 0, token)
        for token in extension_dir.replace("-", ".").split(".")
    ]


@register
class CodexBackend(AgentBackend):
    name = "codex"

    def __init__(self, model: str, settings=None):
        super().__init__(model, settings)
        self.api_key = self.settings.get("api_key") or env_lookup(
            "OPENAI_API_KEY", "openai-api-key", "openai_api_key"
        )
        self.auth_file = Path(
            self.settings.get("auth_file") or Path.home() / ".codex" / "auth.json"
        )
        self.codex_bin = str(self.settings.get("codex_bin") or "")
        self.effort = (self.settings.get("effort") or "").strip()
        if self.effort and self.effort not in _EFFORTS:
            raise ValueError(
                f"invalid codex effort '{self.effort}'; allowed: {sorted(_EFFORTS)}"
            )

    # -- setup ---------------------------------------------------------

    def config_toml(self, workspace: str) -> str:
        lines = [
            f'model = "{self.model}"',
            'approval_policy = "never"',
            'sandbox_mode = "danger-full-access"',
            'web_search = "disabled"',
        ]
        if self.effort:
            lines.append(f'model_reasoning_effort = "{self.effort}"')
        lines += ["", f'[projects."{workspace}"]', 'trust_level = "trusted"', ""]
        return "\n".join(lines)

    def prepare(self, container: Container) -> None:
        if not self.api_key and not self.auth_file.is_file():
            raise RuntimeError(
                "no codex authentication available: set OPENAI_API_KEY or "
                f"provide {self.auth_file}"
            )
        binary = find_codex_binary(self.codex_bin)
        # Codex expects its sibling helpers next to its own executable, so copy
        # the whole bundle directory and expose it through a wrapper.
        container.cp_dir_contents_to(binary.parent, _BUNDLE_DIR)
        container.write_file(
            "/usr/local/bin/codex",
            f'#!/usr/bin/env bash\nexec {_BUNDLE_DIR}/{binary.name} "$@"',
        )
        container.exec(
            f"chmod +x /usr/local/bin/codex {_BUNDLE_DIR}/* 2>/dev/null || true; "
            f"if [[ -x {_BUNDLE_DIR}/rg && ! -e /usr/local/bin/rg ]]; then "
            f"ln -s {_BUNDLE_DIR}/rg /usr/local/bin/rg; fi"
        )
        if not (binary.parent / "rg").is_file():
            host_rg = shutil.which("rg")
            if host_rg:
                container.cp_to(Path(os.path.realpath(host_rg)), "/usr/local/bin/rg")
        if not container.exec("codex --version").ok:
            raise RuntimeError("codex binary does not run inside the container")

        # Codex home: config + auth, kept outside the (possibly read-only) workspace.
        container.write_file(
            f"{_CODEX_HOME}/config.toml", self.config_toml(container.workdir)
        )
        if self.api_key:
            login = container.exec(
                'printf "%s" "$OPENAI_API_KEY" | codex login --with-api-key',
                env={"OPENAI_API_KEY": self.api_key, "CODEX_HOME": _CODEX_HOME},
            )
            if not login.ok:
                raise RuntimeError(
                    f"codex login --with-api-key failed: {login.stderr or login.stdout}"
                )
            print("[codex] auth: OPENAI_API_KEY (API billing)")
        else:
            container.cp_to(self.auth_file, f"{_CODEX_HOME}/auth.json")
            print(f"[codex] auth: ChatGPT-plan auth file ({self.auth_file})")

    # -- one task == one fresh session ----------------------------------

    def run_task(
        self,
        container: Container,
        prompt_container_path: str,
        workspace: str,
        host_log_dir: Path,
        tag: str,
        timeout_s: int,
    ) -> AgentResult:
        host_log_dir.mkdir(parents=True, exist_ok=True)
        raw_traj = f"/tmp/repogen/{tag}.traj.ndjson"
        run_log = f"/tmp/repogen/{tag}.codex.log"
        last_msg = f"/tmp/repogen/{tag}.last_message.txt"

        command = (
            "mkdir -p /tmp/repogen && "
            "CODEX_CMD=(codex exec --json --ephemeral --skip-git-repo-check "
            "--dangerously-bypass-approvals-and-sandbox "
            f"-C '{workspace}' -m \"$CODEX_MODEL\" -o '{last_msg}' "
            f"\"$(cat '{prompt_container_path}')\"); "
            f"timeout -k 60s {timeout_s}s \"${{CODEX_CMD[@]}}\" "
            f"</dev/null >'{raw_traj}' 2>'{run_log}'"
        )
        env = {"CODEX_MODEL": self.model, "CODEX_HOME": _CODEX_HOME}
        result = container.exec(command, env=env, timeout_s=timeout_s + 180)

        host_log = host_log_dir / f"{tag}.codex.log"
        host_traj = host_log_dir / f"{tag}.traj.json"
        container.cp_from(run_log, host_log)
        container.cp_from(last_msg, host_log_dir / f"{tag}.last_message.txt")
        raw_host = host_log_dir / f"{tag}.traj.ndjson"
        if container.cp_from(raw_traj, raw_host):
            ndjson_to_json(raw_host, host_traj)
            raw_host.unlink(missing_ok=True)
        container.exec(f"rm -f '{raw_traj}' '{run_log}' '{last_msg}'")

        note = ""
        if result.exit_code == 124:
            note = f"codex timed out after {timeout_s}s"
        elif result.exit_code == 137:
            note = "codex was force-killed after the timeout grace period (60s)"
        return AgentResult(
            ok=result.exit_code == 0,
            exit_code=result.exit_code,
            log_path=host_log,
            traj_path=host_traj if host_traj.exists() else None,
            note=note,
        )
