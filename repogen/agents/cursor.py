"""Cursor CLI backend.

Mirrors RepoBehave's run_cursor_eval_in_docker.sh: the host cursor-agent
bundle (node + index.js) is copied into the container once, a thin wrapper is
installed at /usr/local/bin/cursor-agent, auth uses CURSOR_API_KEY, and each
task is one non-interactive `cursor-agent -p --force` session whose
stream-json output is persisted as the trajectory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..config import env_lookup
from ..docker_env import Container
from .base import AgentBackend, AgentResult
from . import register


@register
class CursorBackend(AgentBackend):
    name = "cursor"

    def __init__(self, model: str, settings=None):
        super().__init__(model, settings)
        self.api_key = self.settings.get("api_key") or env_lookup("CURSOR_API_KEY")

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

        if self.api_key:
            container.exec(
                "export NO_OPEN_BROWSER=1; "
                'timeout 20s cursor-agent --api-key "$CURSOR_API_KEY" whoami '
                ">/tmp/cursor-whoami.log 2>&1 || true",
                env={"CURSOR_API_KEY": self.api_key},
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
        run_log = f"/tmp/repogen/{tag}.cursor.log"
        auth = '--api-key "$CURSOR_API_KEY" ' if self.api_key else ""

        command = (
            f"mkdir -p /tmp/repogen && "
            f"timeout -k 60s {timeout_s}s "
            f"cursor-agent {auth}-p --force --output-format stream-json "
            f'--model "$CURSOR_MODEL" --workspace "{workspace}" '
            f'"$(cat \'{prompt_container_path}\')" '
            f">'{raw_traj}' 2>'{run_log}'"
        )
        env = {"CURSOR_MODEL": self.model}
        if self.api_key:
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
