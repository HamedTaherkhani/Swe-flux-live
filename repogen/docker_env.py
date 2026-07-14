"""Facade over the docker CLI: one class, one container lifecycle."""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class DockerError(RuntimeError):
    pass


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Container:
    """Context-managed throwaway container kept alive with `tail -f`."""

    def __init__(self, image: str, workdir: str = "/testbed", name: Optional[str] = None):
        self.image = image
        self.workdir = workdir
        self.name = name or f"repogen-{uuid.uuid4().hex[:10]}"
        self._started = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "Container":
        if not self._image_present():
            self._host(["docker", "pull", self.image], check=True)
        self._host(["docker", "rm", "-f", self.name], check=False)
        self._host(
            [
                "docker", "run", "-d", "--name", self.name,
                "-w", self.workdir, self.image, "tail", "-f", "/dev/null",
            ],
            check=True,
        )
        self._started = True
        return self

    def stop(self) -> None:
        if self._started:
            self._host(["docker", "rm", "-f", self.name], check=False)
            self._started = False

    def __enter__(self) -> "Container":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- operations --------------------------------------------------------

    def exec(
        self,
        command: str,
        env: Optional[dict[str, str]] = None,
        timeout_s: Optional[int] = None,
    ) -> ExecResult:
        """Run `bash -lc command` inside the container."""
        argv = ["docker", "exec"]
        for key, value in (env or {}).items():
            argv += ["-e", f"{key}={value}"]
        argv += [self.name, "bash", "-lc", command]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout_s
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(124, e.stdout or "", (e.stderr or "") + "\n[timeout]")
        return ExecResult(proc.returncode, proc.stdout, proc.stderr)

    def cp_to(self, host_path: Path, container_path: str) -> None:
        self.exec(f"mkdir -p '{Path(container_path).parent}'")
        self._host(
            ["docker", "cp", str(host_path), f"{self.name}:{container_path}"],
            check=True,
        )

    def cp_from(self, container_path: str, host_path: Path) -> bool:
        host_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._host(
            ["docker", "cp", f"{self.name}:{container_path}", str(host_path)],
            check=False,
        )
        return result.returncode == 0

    def path_exists(self, container_path: str) -> bool:
        return self.exec(f"test -e '{container_path}'").ok

    def read_file(self, container_path: str) -> str:
        result = self.exec(f"cat '{container_path}'")
        if not result.ok:
            raise DockerError(f"cannot read {container_path}: {result.stderr}")
        return result.stdout

    def write_file(self, container_path: str, content: str) -> None:
        marker = f"REPOGEN_EOF_{uuid.uuid4().hex[:8]}"
        self.exec(f"mkdir -p '{Path(container_path).parent}'")
        result = self.exec(
            f"cat > '{container_path}' <<'{marker}'\n{content}\n{marker}"
        )
        if not result.ok:
            raise DockerError(f"cannot write {container_path}: {result.stderr}")

    # -- helpers -----------------------------------------------------------

    def _image_present(self) -> bool:
        result = self._host(
            ["docker", "image", "inspect", self.image], check=False
        )
        return result.returncode == 0

    @staticmethod
    def _host(argv: list[str], check: bool) -> subprocess.CompletedProcess:
        proc = subprocess.run(argv, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise DockerError(
                f"command failed ({proc.returncode}): {' '.join(argv)}\n{proc.stderr}"
            )
        return proc
