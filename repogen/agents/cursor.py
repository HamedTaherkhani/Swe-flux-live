"""Cursor CLI backend.

Mirrors RepoBehave's run_cursor_eval_in_docker.sh: the host cursor-agent
bundle (node + index.js) is copied into the container once, a thin wrapper is
installed at /usr/local/bin/cursor-agent, and each task is one non-interactive
`cursor-agent -p --force` session whose stream-json output is persisted as the
trajectory.

Auth: the host's subscription session (`~/.config/cursor/auth.json`, created by
`cursor-agent login`) is copied into the container and used when present —
sessions then bill the Cursor plan instead of API credits. Falls back to
CURSOR_API_KEY. Pass settings["auth"] = "api_key" to force the key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..config import env_lookup
from ..docker_env import Container
from .base import AgentBackend, AgentResult
from . import register

# Where the cursor CLI stores the logged-in session on the host.
HOST_AUTH_FILE = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "cursor" / "auth.json"


@register
class CursorBackend(AgentBackend):
    name = "cursor"

    def __init__(self, model: str, settings=None):
        super().__init__(model, settings)
        self.api_key = self.settings.get("api_key") or env_lookup("CURSOR_API_KEY")
        # Subscription session wins over the API key (as for claude-code), so
        # a logged-in machine does not silently spend API credits.
        forced = (self.settings.get("auth") or "").strip().lower()
        auth_file = self.settings.get("auth_file")
        self.auth_file = Path(auth_file) if auth_file else HOST_AUTH_FILE
        self.use_subscription = (
            forced != "api_key"
            and self.auth_file.is_file()
        )
        if forced == "subscription" and not self.auth_file.is_file():
            raise RuntimeError(
                f"cursor subscription auth requested but {self.auth_file} not found; "
                "run `cursor-agent login` on the host first"
            )

    # -- setup ---------------------------------------------------------

    def prepare(self, container: Container) -> None:
        if container.exec("command -v cursor-agent").ok:
            return
        bundle_dir = self._host_bundle_dir()
        container.exec("mkdir -p /opt/cursor-agent")
        subprocess.run(
            ["docker", "cp", f"{bundle_dir}/.", f"{container.name}:/opt/cursor-agent/"],
            check=True,
        )
        wrapper = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'exec /opt/cursor-agent/node --use-system-ca /opt/cursor-agent/index.js "$@"\n'
        )
        container.write_file("/usr/local/bin/cursor-agent", wrapper)
        container.exec("chmod +x /usr/local/bin/cursor-agent")
        if not container.exec("command -v cursor-agent").ok:
            raise RuntimeError("failed to install cursor-agent into container")

        if self.use_subscription:
            self._install_session(container)
            print("[cursor] auth: subscription session (~/.config/cursor/auth.json)")
            container.exec(
                "export NO_OPEN_BROWSER=1; timeout 20s cursor-agent whoami "
                ">/tmp/cursor-whoami.log 2>&1 || true"
            )
        elif self.api_key:
            print("[cursor] auth: CURSOR_API_KEY (API billing)")
            container.exec(
                "export NO_OPEN_BROWSER=1; "
                'timeout 20s cursor-agent --api-key "$CURSOR_API_KEY" whoami '
                ">/tmp/cursor-whoami.log 2>&1 || true",
                env={"CURSOR_API_KEY": self.api_key},
            )
        else:
            print(
                "[cursor] WARNING: no auth found — run `cursor-agent login` or set "
                "CURSOR_API_KEY; sessions will fail to authenticate"
            )

    def _install_session(self, container: Container) -> None:
        """Copy the host's logged-in session into the container's cursor config."""
        home = (container.exec("echo -n $HOME").stdout or "/root").strip() or "/root"
        dest = f"{home}/.config/cursor/auth.json"
        container.exec(f"mkdir -p '{home}/.config/cursor'")
        container.cp_to(self.auth_file, dest)
        container.exec(f"chmod 600 '{dest}'")

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
        run_log = f"/tmp/repogen/{tag}.cursor.log"
        # With a session installed, cursor-agent reads auth from its config;
        # passing --api-key would override it and bill API credits instead.
        auth = "" if self.use_subscription else (
            '--api-key "$CURSOR_API_KEY" ' if self.api_key else ""
        )

        command = (
            f"mkdir -p /tmp/repogen && "
            f"timeout -k 60s {timeout_s}s "
            f"cursor-agent {auth}-p --force --output-format stream-json "
            f'--model "$CURSOR_MODEL" --workspace "{workspace}" '
            f'"$(cat \'{prompt_container_path}\')" '
            f">'{raw_traj}' 2>'{run_log}'"
        )
        env = {"CURSOR_MODEL": self.model}
        if self.api_key and not self.use_subscription:
            env["CURSOR_API_KEY"] = self.api_key

        # host-side timeout is a safety net over the in-container `timeout`
        result = container.exec(command, env=env, timeout_s=timeout_s + 180)

        host_log = host_log_dir / f"{tag}.cursor.log"
        host_traj = host_log_dir / f"{tag}.traj.json"
        container.cp_from(run_log, host_log)
        raw_host = host_log_dir / f"{tag}.traj.ndjson"
        if container.cp_from(raw_traj, raw_host):
            self._ndjson_to_json(raw_host, host_traj)
            raw_host.unlink(missing_ok=True)
        container.exec(f"rm -f '{raw_traj}' '{run_log}'")

        note = ""
        if result.exit_code == 124:
            note = f"cursor-agent timed out after {timeout_s}s"
        return AgentResult(
            ok=result.exit_code == 0,
            exit_code=result.exit_code,
            log_path=host_log,
            traj_path=host_traj if host_traj.exists() else None,
            note=note,
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _host_bundle_dir() -> str:
        exe = shutil.which("cursor-agent")
        if not exe:
            raise RuntimeError(
                "local 'cursor-agent' not found on host; install it first "
                "(https://cursor.com/docs/cli/installation)"
            )
        real = Path(exe).resolve()
        bundle = real.parent
        if not (bundle / "index.js").exists() or not (bundle / "node").exists():
            raise RuntimeError(f"cursor-agent bundle incomplete at {bundle}")
        return str(bundle)

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
