"""Claude Code CLI backend.

Mirrors RepoBehave's run_claude_code_eval_in_docker.sh: the `claude` CLI is
installed inside the container (native installer, npm fallback), auth uses
CLAUDE_CODE_OAUTH_TOKEN (subscription; create one with `claude setup-token`)
or ANTHROPIC_API_KEY (pay-per-token API) — the OAuth token wins when both are
set — and each task is one non-interactive `claude -p` session
whose stream-json output is persisted as the trajectory. Root containers get
`--permission-mode acceptEdits --allowedTools "Bash(*)"` (bypassPermissions is
blocked for root); non-root gets `--dangerously-skip-permissions`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import env_file_lookup, env_lookup
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
        oauth_names = (
            "CLAUDE_CODE_OAUTH_TOKEN", "claude-code-oauth-token", "claude_code_oauth_token"
        )
        # Trust only tokens the user put in the .env FILE. A CLAUDE_CODE_OAUTH_TOKEN
        # inherited from the process environment is usually the session-internal
        # token of a Claude Code instance running repogen itself — invalid inside
        # the solver container (401 Invalid bearer token).
        self.oauth_token = self.settings.get("oauth_token") or env_file_lookup(*oauth_names)
        self.api_key = self.settings.get("api_key") or env_lookup(
            "ANTHROPIC_API_KEY", "anthropic-api-key", "anthropic_api_key"
        )
        self._inherited_token_ignored = False
        if not self.oauth_token:
            inherited = env_lookup(*oauth_names)
            if inherited and not self.api_key:
                self.oauth_token = inherited  # last resort: nothing else to auth with
            elif inherited:
                self._inherited_token_ignored = True
        # Tokens from `claude setup-token` start with sk-ant-oat. Anything else
        # (a pasted session key, an API key in the wrong slot) guarantees
        # 401s that would fail EVERY instance — fall back to the API key.
        self._auth_warning = ""
        if self.oauth_token and not self.oauth_token.startswith("sk-ant-oat"):
            hint = (
                "CLAUDE_CODE_OAUTH_TOKEN does not look like a Claude Code OAuth "
                "token (expected it to start with 'sk-ant-oat'); create one with "
                "`claude setup-token`."
            )
            if self.api_key:
                self._auth_warning = hint + " Falling back to ANTHROPIC_API_KEY."
                self.oauth_token = ""
            else:
                self._auth_warning = hint + " No API-key fallback; auth will likely fail."
        self.extra_args = self.settings.get("extra_args", "")
        # Reasoning effort for the claude CLI (--effort). Empty = CLI default
        # (high on current Claude models).
        effort = (self.settings.get("effort") or "").strip()
        if effort:
            allowed = {"low", "medium", "high", "xhigh", "max"}
            if effort not in allowed:
                raise ValueError(
                    f"invalid claude-code effort '{effort}'; allowed: {sorted(allowed)}"
                )
            self.extra_args = f"{self.extra_args} --effort {effort}".strip()

    # -- setup ---------------------------------------------------------

    def prepare(self, container: Container) -> None:
        result = container.exec(_INSTALL_SCRIPT, timeout_s=900)
        if not result.ok:
            raise RuntimeError(
                f"failed to install claude CLI in container: {result.stderr or result.stdout}"
            )
        if self._auth_warning:
            print(f"[claude-code] WARNING: {self._auth_warning}")
        if self.oauth_token:
            print("[claude-code] auth: CLAUDE_CODE_OAUTH_TOKEN (subscription)")
        elif self.api_key:
            print("[claude-code] auth: ANTHROPIC_API_KEY (API billing)")
            if self._inherited_token_ignored:
                print(
                    "[claude-code] note: ignoring CLAUDE_CODE_OAUTH_TOKEN inherited "
                    "from the process environment (not in .env) — add "
                    "claude-code-oauth-token to .env to use subscription auth"
                )
        else:
            print(
                "[claude-code] WARNING: no CLAUDE_CODE_OAUTH_TOKEN or "
                "ANTHROPIC_API_KEY found (env or .env); non-interactive "
                "sessions will likely fail to authenticate"
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
        # Subscription OAuth token wins over the API key: with both set the CLI
        # would bill the API key, defeating the point of setting a token.
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        elif self.api_key:
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
