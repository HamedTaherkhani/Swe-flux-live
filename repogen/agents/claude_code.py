"""Claude Code CLI backend.

Mirrors RepoBehave's run_claude_code_eval_in_docker.sh: the `claude` CLI is
installed inside the container (native installer, npm fallback), auth uses
ANTHROPIC_API_KEY, and each task is one non-interactive `claude -p` session
whose stream-json output is persisted as the trajectory. Root containers get
`--permission-mode acceptEdits --allowedTools "Bash(*)"` (bypassPermissions is
blocked for root); non-root gets `--dangerously-skip-permissions`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import env_lookup
from ..docker_env import Container
from .base import AgentBackend, AgentResult
from . import register

_INSTALL_SCRIPT = r"""
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if command -v claude >/dev/null 2>&1; then
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/tmp/claude-apt-update.log 2>&1 || true
    apt-get install -y curl ca-certificates >/tmp/claude-apt-install.log 2>&1 || true
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl ca-certificates >/tmp/claude-apk-install.log 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y curl ca-certificates >/tmp/claude-dnf-install.log 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y curl ca-certificates >/tmp/claude-yum-install.log 2>&1 || true
  fi
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash >/tmp/claude-native-install.log 2>&1 || true
fi

export PATH="$HOME/.local/bin:$PATH"
if ! command -v claude >/dev/null 2>&1 && [[ -x "$HOME/.local/bin/claude" ]]; then
  mkdir -p /usr/local/bin >/dev/null 2>&1 || true
  ln -sf "$HOME/.local/bin/claude" /usr/local/bin/claude >/dev/null 2>&1 || true
fi

if command -v claude >/dev/null 2>&1; then
  exit 0
fi

# Fallback installer: npm package.
if ! command -v npm >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/tmp/claude-apt-update.log 2>&1 || true
    apt-get install -y nodejs npm >/tmp/claude-apt-install.log 2>&1 || true
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache nodejs npm >/tmp/claude-apk-install.log 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y nodejs npm >/tmp/claude-dnf-install.log 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y nodejs npm >/tmp/claude-yum-install.log 2>&1 || true
  fi
fi

if command -v npm >/dev/null 2>&1; then
  npm install -g @anthropic-ai/claude-code >/tmp/claude-npm-install.log 2>&1 || true
fi

export PATH="$HOME/.local/bin:$PATH"
if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: failed to install Claude CLI in container." >&2
  exit 1
fi
"""


@register
class ClaudeCodeBackend(AgentBackend):
    name = "claude-code"

    def __init__(self, model: str, settings=None):
        super().__init__(model, settings)
        self.api_key = self.settings.get("api_key") or env_lookup(
            "ANTHROPIC_API_KEY", "anthropic-api-key", "anthropic_api_key"
        )
        self.extra_args = self.settings.get("extra_args", "")

    # -- setup ---------------------------------------------------------

    def prepare(self, container: Container) -> None:
        result = container.exec(_INSTALL_SCRIPT, timeout_s=900)
        if not result.ok:
            raise RuntimeError(
                f"failed to install claude CLI in container: {result.stderr or result.stdout}"
            )
        if not self.api_key:
            print(
                "[claude-code] WARNING: no ANTHROPIC_API_KEY found (env or .env); "
                "non-interactive sessions will likely fail to authenticate"
            )

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
        run_log = f"/tmp/repogen/{tag}.claude.log"

        command = (
            'export PATH="$HOME/.local/bin:$PATH"; '
            f"mkdir -p /tmp/repogen && cd '{workspace}' && "
            "CLAUDE_CMD=(claude -p --verbose --output-format stream-json "
            '--model "$CLAUDE_MODEL"); '
            'if [[ "$(id -u)" -eq 0 ]]; then '
            'CLAUDE_CMD+=(--permission-mode acceptEdits --allowedTools "Bash(*)"); '
            "else CLAUDE_CMD+=(--dangerously-skip-permissions); fi; "
            'if [[ -n "${CLAUDE_EXTRA_ARGS:-}" ]]; then '
            "CLAUDE_CMD+=(${CLAUDE_EXTRA_ARGS}); fi; "
            f"CLAUDE_CMD+=(-- \"$(cat '{prompt_container_path}')\"); "
            f"timeout -k 60s {timeout_s}s \"${{CLAUDE_CMD[@]}}\" "
            f">'{raw_traj}' 2>'{run_log}'"
        )
        env = {"CLAUDE_MODEL": self.model}
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        if self.extra_args:
            env["CLAUDE_EXTRA_ARGS"] = self.extra_args

        result = container.exec(command, env=env, timeout_s=timeout_s + 180)

        host_log = host_log_dir / f"{tag}.claude.log"
        host_traj = host_log_dir / f"{tag}.traj.json"
        container.cp_from(run_log, host_log)
        raw_host = host_log_dir / f"{tag}.traj.ndjson"
        if container.cp_from(raw_traj, raw_host):
            self._ndjson_to_json(raw_host, host_traj)
            raw_host.unlink(missing_ok=True)
        container.exec(f"rm -f '{raw_traj}' '{run_log}'")

        note = ""
        if result.exit_code == 124:
            note = f"claude timed out after {timeout_s}s"
        return AgentResult(
            ok=result.exit_code == 0,
            exit_code=result.exit_code,
            log_path=host_log,
            traj_path=host_traj if host_traj.exists() else None,
            note=note,
        )

    @staticmethod
    def _ndjson_to_json(src: Path, dst: Path) -> None:
        events = []
        with src.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"type": "raw_line", "text": line})
        with dst.open("w", encoding="utf-8") as f:
            json.dump({"events": events}, f, indent=2, sort_keys=True)
            f.write("\n")
